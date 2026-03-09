import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from supabase import create_client, Client

# ==========================================
# DEEL 1: CONFIGURATIE & MODELLEN (De Fundering)
# ==========================================

st.set_page_config(page_title="vvXP Tracker", page_icon="⚡", layout="wide")

st.markdown("""
    <style>
    .stButton>button { border-radius: 20px; font-weight: bold; }
    .stProgress .st-bo { background-color: #00f2fe; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

CLASSES: List[str] = ["5HW", "5ECWI", "5ECMT", "5MT", "5WEMT", "5WEWI", "5WEWIC", "6ECMT", "6MT", "6WEWI", "6ECWI", "6HW"]

# De vaste schaal (woorden naar getallen voor wiskundige berekeningen)
SCALE_OPTIONS = ["Not at all", "Sometimes", "Regularly", "Always"]
SCALE_MAP = {
    "Not at all": 1,
    "Sometimes": 2,
    "Regularly": 3,
    "Always": 4
}

# De fallback gemiddeldes (voor als de database nog geen echte klas-data heeft)
CLASS_AVG_SKILLS: Dict[str, float] = {
    'Participation': 2.5, 
    'Full Sentences': 2.5, 
    'Exact Words': 2.5, 
    'English Only': 2.5
}

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
            st.error(f"Systeemfout: Configuratie {e} ontbreekt.")
            st.stop()

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def register_student(self, first_name: str, student_class: str, reg_code: str) -> bool:
        user_key = first_name.lower().strip()
        try:
            response = self.client.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) > 0:
                return False  
            
            new_student = {
                "user_key": user_key,
                "first_name": first_name,
                "class_name": student_class,
                "hashed_code": self._hash_password(reg_code)
            }
            self.client.table(self.table_students).insert(new_student).execute()
            return True
        except Exception as e:
            st.error(f"Er ging iets mis in de machinekamer: {e}")
            return False

    def login_student(self, first_name: str, reg_code: str) -> Optional[StudentProfile]:
        user_key = first_name.lower().strip()
        try:
            response = self.client.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) == 0:
                return None  
                
            student_data = response.data[0]
            if student_data["hashed_code"] == self._hash_password(reg_code):
                return StudentProfile(
                    first_name=student_data["first_name"],
                    student_class=student_data["class_name"],
                    is_authenticated=True,
                    user_key=user_key
                )
            return None 
        except Exception as e:
            st.error(f"Systeem kon login niet verwerken: {e}")
            return None

    def log_pulse(self, user_key: str, class_name: str, scores: Dict[str, int]) -> bool:
        """Slaat de ingevulde scorelijst op in de database."""
        try:
            log_entry = {
                "user_key": user_key,
                "class_name": class_name,
                "participation": scores["participation"],
                "full_sentences": scores["full_sentences"],
                "exact_words": scores["exact_words"],
                "english_only": scores["english_only"]
            }
            self.client.table(self.table_logs).insert(log_entry).execute()
            return True
        except Exception as e:
            st.error(f"Kon gegevens niet opslaan: {e}")
            return False

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
    st.title("⚡ Welcome to the vvXP Tracker")
    st.markdown("Track your progress, earn XP and improve your English.")
    
    tab_login, tab_register = st.tabs(["🔐 Login", "📝 Register"])
    
    with tab_register:
        with st.form("register_form"):
            new_name = st.text_input("First Name (This will be your login)")
            new_class = st.selectbox("Class", CLASSES)
            new_code = st.text_input("Create a Registration Code (Password)", type="password")
            
            if st.form_submit_button("Create Profile"):
                if new_name and new_code:
                    if db_butler.register_student(new_name, new_class, new_code):
                        st.success("Profile created! Go to the Login tab.")
                    else:
                        st.error("This name is already taken. Choose another or login.")
                else:
                    st.warning("Please fill in all fields!")

    with tab_login:
        with st.form("login_form"):
            login_name = st.text_input("First Name")
            login_code = st.text_input("Registration Code", type="password")
            
            if st.form_submit_button("Enter vvXP Tracker"):
                user_profile = db_butler.login_student(login_name, login_code)
                if user_profile:
                    st.session_state.current_user = user_profile
                    st.rerun() 
                else:
                    st.error("Oops! Wrong name or code.")

def generate_feedback_text(skill_name: str, student_score: int, class_avg: float) -> str:
    """Genereert slimme, persoonlijke feedback in het Engels."""
    if student_score > class_avg:
        return f"🌟 **{skill_name}**: Awesome! You put more effort into this than the average student in your class."
    elif student_score == class_avg or (student_score >= 3 and class_avg >= 3):
        return f"✅ **{skill_name}**: Good job! You are right on track with the rest of your class."
    else:
        return f"🚀 **{skill_name}**: This is your growth opportunity! Try to focus a bit more on this next time."

def render_radar_chart(student_scores: List[int]) -> None:
    st.subheader("Your Growth Radar")
    
    class_skills = list(CLASS_AVG_SKILLS.values())
    categories = list(CLASS_AVG_SKILLS.keys())
    
    fig_radar = go.Figure()
    
    fig_radar.add_trace(go.Scatterpolar(
        r=class_skills, theta=categories, fill='toself', 
        name=f'{st.session_state.current_user.student_class} Average',
        line_color='rgba(255, 255, 255, 0.4)', fillcolor='rgba(255, 255, 255, 0.1)'
    ))
    
    fig_radar.add_trace(go.Scatterpolar(
        r=student_scores, theta=categories, fill='toself', name='Your Score',
        line_color='#00f2fe', fillcolor='rgba(0, 242, 254, 0.4)'
    ))
    
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 4], gridcolor='rgba(255,255,255,0.2)')),
        showlegend=True, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=20, b=20)
    )
    st.plotly_chart(fig_radar, use_container_width=True)

def render_dashboard() -> None:
    user = st.session_state.current_user
    
    col1, col2 = st.columns([8, 1])
    with col1:
        st.title(f"Sup {user.first_name}! 👋")
    with col2:
        if st.button("Logout"):
            st.session_state.current_user = StudentProfile(first_name="", student_class="")
            st.session_state.recent_scores = None
            st.rerun()
            
    st.markdown(f"**Class:** {user.student_class} | **Status:** vvXP Tracking Active")
    st.markdown("---")
    
    tab_pulse, tab_reflection = st.tabs(["🔥 Pulse Check & Dashboard", "📝 Post-Evaluation Reflection"])
    
    with tab_pulse:
        col_form, col_charts = st.columns([1, 1.2]) 
        
        with col_form:
            st.subheader("Weekly Pulse Check")
            with st.form("pulse_form"):
                
                q1 = st.select_slider("1. How active were you in class today?", options=SCALE_OPTIONS)
                q2 = st.select_slider("2. Did you try to answer in full sentences?", options=SCALE_OPTIONS)
                q3 = st.select_slider("3. Did you search for the EXACT right words?", options=SCALE_OPTIONS)
                q4 = st.select_slider("4. Did you speak English the entire time?", options=SCALE_OPTIONS)
                
                if st.form_submit_button("🚀 Submit Pulse"):
                    # Vertaal de tekst ("Always") naar een getal (4)
                    scores_dict = {
                        "participation": SCALE_MAP[q1],
                        "full_sentences": SCALE_MAP[q2],
                        "exact_words": SCALE_MAP[q3],
                        "english_only": SCALE_MAP[q4]
                    }
                    
                    if db_butler.log_pulse(user.user_key, user.student_class, scores_dict):
                        st.success("Data successfully logged to the database!")
                        # Sla de scores tijdelijk op in het geheugen voor de grafiek en feedback
                        st.session_state.recent_scores = scores_dict
                        st.rerun()

        with col_charts:
            # Als de leerling zojuist iets heeft ingevuld, laten we dat zien!
            if st.session_state.recent_scores:
                scores = st.session_state.recent_scores
                student_array = [
                    scores["participation"], 
                    scores["full_sentences"], 
                    scores["exact_words"], 
                    scores["english_only"]
                ]
                
                render_radar_chart(student_array)
                
                # Toon de persoonlijke feedback
                st.subheader("Your AI Coach Feedback")
                st.info(generate_feedback_text("Participation", scores["participation"], CLASS_AVG_SKILLS["Participation"]))
                st.info(generate_feedback_text("Full Sentences", scores["full_sentences"], CLASS_AVG_SKILLS["Full Sentences"]))
                st.info(generate_feedback_text("Exact Words", scores["exact_words"], CLASS_AVG_SKILLS["Exact Words"]))
                st.info(generate_feedback_text("English Only", scores["english_only"], CLASS_AVG_SKILLS["English Only"]))
            else:
                st.info("👈 Fill in your Pulse Check on the left to see your Radar and personalized feedback!")

    with tab_reflection:
         st.info("The Post-Evaluation Reflection tab is under construction! 🚧")

# ==========================================
# DEEL 4: DE MOTOR (Het startpunt)
# ==========================================

def main() -> None:
    init_session()
    if not st.session_state.current_user.is_authenticated:
        render_auth_screen()
    else:
        render_dashboard()

if __name__ == "__main__":
    main()
