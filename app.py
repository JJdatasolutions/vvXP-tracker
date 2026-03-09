import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from supabase import create_client, Client

# ==========================================
# DEEL 1: CONFIGURATIE & MODELLEN
# ==========================================

st.set_page_config(page_title="vvXP Tracker", page_icon="⚡", layout="wide")

# Lichte, moderne styling
st.markdown("""
    <style>
    .stApp { background-color: #f4f7f6; color: #2b2b2b; }
    
    .stButton>button { 
        border-radius: 8px; font-weight: 600; background-color: #4A90E2;
        color: white; border: none; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: all 0.3s ease; padding: 0.5rem 2rem;
    }
    .stButton>button:hover {
        transform: translateY(-2px); box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        background-color: #357ABD;
    }
    
    div[data-testid="stForm"] {
        background-color: #ffffff; border-radius: 12px; padding: 2rem;
        border: 1px solid #e1e4e8; box-shadow: 0 4px 15px rgba(0,0,0,0.04);
    }
    div[data-testid="stForm"] p, div[data-testid="stForm"] label { color: #333333 !important; }
    
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

CLASSES: List[str] = ["5HW", "5ECWI", "5ECMT", "5MT", "5WEMT", "5WEWI", "5WEWIC", "6ECMT", "6MT", "6WEWI", "6ECWI", "6HW"]

MAP_ACTIVITY = { "Very passive": 1, "Rather passive": 2, "Neutral": 3, "Active": 4, "Very active": 5 }
MAP_FREQ = { "Not at all": 1, "Rarely": 2, "Sometimes": 3, "Usually": 4, "Always": 5 }
MAP_ENG = { "Mostly Dutch": 1, "More Dutch than English": 2, "Half/Half": 3, "Mostly English": 4, "100% English": 5 }
MAP_ENJOY = { "Very boring": 1, "Rather boring": 2, "Neutral": 3, "Stimulating": 4, "Very stimulating": 5 }

@dataclass
class StudentProfile:
    first_name: str
    student_class: str
    is_authenticated: bool = False
    user_key: str = ""

# ==========================================
# DEEL 2: DE BUTLER (Supabase Service Layer)
# ==========================================

class SupabaseButler:
    def __init__(self) -> None:
        try:
            url: str = st.secrets["SUPABASE_URL"]
            key: str = st.secrets["SUPABASE_KEY"]
            self.client: Client = create_client(url, key)
            self.table_students: str = "students"
            self.table_logs: str = "pulse_logs"
        except KeyError as e:
            st.error(f"Systeemfout: Configuratie {e} ontbreekt in geheimen.")
            st.stop()

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def register_student(self, first_name: str, student_class: str, reg_code: str) -> bool:
        user_key = first_name.lower().strip()
        try:
            response = self.client.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) > 0: return False  
            
            new_student = { "user_key": user_key, "first_name": first_name, "class_name": student_class, "hashed_code": self._hash_password(reg_code) }
            self.client.table(self.table_students).insert(new_student).execute()
            return True
        except Exception as e:
            st.error(f"Machinekamer fout: {e}")
            return False

    def login_student(self, first_name: str, reg_code: str) -> Optional[StudentProfile]:
        user_key = first_name.lower().strip()
        try:
            response = self.client.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) == 0: return None  
                
            student_data = response.data[0]
            if student_data["hashed_code"] == self._hash_password(reg_code):
                return StudentProfile(first_name=student_data["first_name"], student_class=student_data["class_name"], is_authenticated=True, user_key=user_key)
            return None 
        except Exception as e:
            st.error(f"Login fout: {e}")
            return None

    def log_pulse(self, user_key: str, class_name: str, scores: Dict[str, int]) -> bool:
        try:
            log_entry = {
                "user_key": user_key, "class_name": class_name,
                "participation": scores["participation"], "full_sentences": scores["full_sentences"],
                "exact_words": scores["exact_words"], "english_only": scores["english_only"],
                "lesson_enjoyment": scores["lesson_enjoyment"]
            }
            self.client.table(self.table_logs).insert(log_entry).execute()
            return True
        except Exception as e:
            st.error(f"Kon gegevens niet opslaan: {e}")
            return False

    def get_global_averages(self) -> List[float]:
        """
        Berekent het gemiddelde van alle leerlingen in de database.
        Als er nog niemand heeft ingevuld, vallen we terug op een score van 3.0.
        """
        try:
            response = self.client.table(self.table_logs).select("*").execute()
            data = response.data
            
            if not data:
                return [3.0, 3.0, 3.0, 3.0, 3.0] # Fallback
                
            n = len(data)
            avg_part = sum(row["participation"] for row in data) / n
            avg_full = sum(row["full_sentences"] for row in data) / n
            avg_exact = sum(row["exact_words"] for row in data) / n
            avg_eng = sum(row["english_only"] for row in data) / n
            avg_enjoy = sum(row["lesson_enjoyment"] for row in data) / n
            
            return [avg_part, avg_full, avg_exact, avg_eng, avg_enjoy]
        except Exception as e:
            st.warning("Live gemiddelde ophalen mislukt, we gebruiken fallback.")
            return [3.0, 3.0, 3.0, 3.0, 3.0]

db_butler = SupabaseButler()

# ==========================================
# DEEL 3: SCHERMEN & FEEDBACK LOGICA
# ==========================================

def init_session() -> None:
    if 'current_user' not in st.session_state:
        st.session_state.current_user = StudentProfile(first_name="", student_class="")
    if 'recent_scores' not in st.session_state:
        st.session_state.recent_scores = None

def render_auth_screen() -> None:
    st.markdown("<h1 style='text-align: center; color: #4A90E2;'>⚡ vvXP Tracker</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #666;'>Track your progress, earn XP and level up your English.</p>", unsafe_allow_html=True)
    st.write("---")
    
    col_space1, col_main, col_space2 = st.columns([1, 2, 1])
    with col_main:
        tab_login, tab_register = st.tabs(["🔐 Login", "📝 Register"])
        with tab_register:
            with st.form("register_form"):
                new_name = st.text_input("First Name (This will be your login)")
                new_class = st.selectbox("Class", CLASSES)
                new_code = st.text_input("Create a Registration Code (Password)", type="password")
                if st.form_submit_button("Create Profile"):
                    if new_name and new_code:
                        if db_butler.register_student(new_name, new_class, new_code): st.success("Profile created! Go to the Login tab.")
                        else: st.error("This name is already taken. Choose another or login.")
                    else: st.warning("Please fill in all fields!")

        with tab_login:
            with st.form("login_form"):
                login_name = st.text_input("First Name")
                login_code = st.text_input("Registration Code", type="password")
                if st.form_submit_button("Enter vvXP Tracker"):
                    user_profile = db_butler.login_student(login_name, login_code)
                    if user_profile:
                        st.session_state.current_user = user_profile
                        st.rerun() 
                    else: st.error("Oops! Wrong name or code.")

def generate_feedback_text(skill_name: str, student_score: int, global_avg: float) -> str:
    if student_score > global_avg: return f"🌟 **{skill_name}**: Awesome! You scored higher than the global average ({global_avg:.1f})."
    elif student_score == round(global_avg) or (student_score >= 4 and global_avg >= 4): return f"✅ **{skill_name}**: Solid work! You are right on track."
    else: return f"🚀 **{skill_name}**: Room to grow! The average is {global_avg:.1f}. Try to push a bit more next time."

def render_radar_chart(student_scores: List[int], global_averages: List[float]) -> None:
    categories = ['Participation', 'Full Sentences', 'Exact Words', 'English Only', 'Enjoyment']
    fig_radar = go.Figure()
    
    # Algemeen Gemiddelde (Subtiel grijs op de achtergrond)
    fig_radar.add_trace(go.Scatterpolar(
        r=global_averages, theta=categories, fill='toself', 
        name='All Students Average',
        line_color='rgba(150, 150, 150, 0.5)', fillcolor='rgba(200, 200, 200, 0.2)',
        line_shape='spline', line_width=2
    ))
    
    # Jouw Score (Knalt eruit in fel blauw)
    fig_radar.add_trace(go.Scatterpolar(
        r=student_scores, theta=categories, fill='toself', name='Your Score',
        line_color='#4A90E2', fillcolor='rgba(74, 144, 226, 0.3)',
        line_shape='spline', line_width=4
    ))
    
    fig_radar.update_layout(
        template="plotly_white",
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 5], gridcolor='#e5e5e5', tickfont=dict(color='#888', size=10), tickangle=0),
            angularaxis=dict(gridcolor='#e5e5e5', tickfont=dict(size=13, color='#333', weight='bold'))
        ),
        showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=60, r=60, t=40, b=40)
    )
    st.plotly_chart(fig_radar, use_container_width=True)

def render_dashboard() -> None:
    user = st.session_state.current_user
    safe_user_key = getattr(user, 'user_key', user.first_name.lower().strip())
    
    col1, col2 = st.columns([8, 1])
    with col1:
        st.markdown(f"<h2>Sup <span style='color: #4A90E2;'>{user.first_name}</span>! 👋</h2>", unsafe_allow_html=True)
        st.caption(f"Class: {user.student_class} | Status: Online")
    with col2:
        if st.button("Logout"):
            st.session_state.current_user = StudentProfile(first_name="", student_class="")
            st.session_state.recent_scores = None
            st.rerun()
            
    st.write("---")
    
    tab_pulse, tab_reflection = st.tabs(["🔥 Pulse Check", "📝 Reflection"])
    
    with tab_pulse:
        col_form, col_space, col_charts = st.columns([1.2, 0.1, 1.5]) 
        
        with col_form:
            st.markdown("### Weekly Pulse")
            with st.form("pulse_form"):
                q1 = st.select_slider("1. How active were you in class today?", options=list(MAP_ACTIVITY.keys()))
                st.write("") 
                q2 = st.select_slider("2. Did you try to answer in full sentences?", options=list(MAP_FREQ.keys()))
                st.write("")
                q3 = st.select_slider("3. Did you search for the EXACT right words?", options=list(MAP_FREQ.keys()))
                st.write("")
                q4 = st.select_slider("4. Did you speak English the entire time?", options=list(MAP_ENG.keys()))
                st.write("")
                q5 = st.select_slider("5. How stimulating was today's lesson?", options=list(MAP_ENJOY.keys()))
                
                st.write("---")
                if st.form_submit_button("🚀 Submit & Earn XP"):
                    scores_dict = {
                        "participation": MAP_ACTIVITY[q1], "full_sentences": MAP_FREQ[q2],
                        "exact_words": MAP_FREQ[q3], "english_only": MAP_ENG[q4], "lesson_enjoyment": MAP_ENJOY[q5]
                    }
                    if db_butler.log_pulse(safe_user_key, user.student_class, scores_dict):
                        st.success("Awesome! Data logged and XP earned! 🎯")
                        st.session_state.recent_scores = scores_dict
                        st.rerun()

        with col_charts:
            if st.session_state.recent_scores:
                scores = st.session_state.recent_scores
                student_array = [
                    scores["participation"], scores["full_sentences"], 
                    scores["exact_words"], scores["english_only"], scores["lesson_enjoyment"]
                ]
                
                # Haal het live gemiddelde op uit de database
                global_averages = db_butler.get_global_averages()
                
                st.markdown("### Your Growth Radar")
                render_radar_chart(student_array, global_averages)
                
                st.markdown("### AI Coach Feedback")
                st.info(generate_feedback_text("Participation", scores["participation"], global_averages[0]))
                st.info(generate_feedback_text("Full Sentences", scores["full_sentences"], global_averages[1]))
                st.info(generate_feedback_text("Exact Words", scores["exact_words"], global_averages[2]))
                st.info(generate_feedback_text("English Only", scores["english_only"], global_averages[3]))
                
            else:
                st.info("👈 Fill in your Pulse Check on the left to unlock your Radar and personalized feedback!")

    with tab_reflection:
         st.markdown("### Post-Evaluation Reflection")
         st.info("This area is under construction! 🚧 Check back later to reflect on your major tasks.")

def main() -> None:
    init_session()
    if not st.session_state.current_user.is_authenticated:
        render_auth_screen()
    else:
        render_dashboard()

if __name__ == "__main__":
    main()
