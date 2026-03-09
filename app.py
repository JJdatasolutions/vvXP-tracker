import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from supabase import create_client, Client
import google.generativeai as genai

# ==========================================
# DEEL 1: CONFIGURATIE & MODELLEN
# ==========================================

st.set_page_config(page_title="vvXP Tracker", page_icon="⚡", layout="wide")

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
    div[data-testid="stForm"], .teacher-card {
        background-color: #ffffff; border-radius: 12px; padding: 2rem;
        border: 1px solid #e1e4e8; box-shadow: 0 4px 15px rgba(0,0,0,0.04);
        margin-bottom: 1rem;
    }
    div[data-testid="stForm"] p, div[data-testid="stForm"] label { color: #333333 !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

CLASSES: List[str] = ["5HW", "5ECWI", "5ECMT", "5MT", "5WEMT", "5WEWI", "5WEWIC", "6ECMT", "6MT", "6WEWI", "6ECWI", "6HW"]
SKILLS = ["Writing", "Speaking", "Reading", "Listening", "Knowledge"]
UNITS = ["U3", "U4", "U5", "U6"]

MAP_ACTIVITY = { "Very passive": 1, "Rather passive": 2, "Neutral": 3, "Active": 4, "Very active": 5 }
MAP_FREQ = { "Not at all": 1, "Rarely": 2, "Sometimes": 3, "Usually": 4, "Always": 5 }
MAP_ENG = { "Mostly Dutch": 1, "More Dutch than English": 2, "Half/Half": 3, "Mostly English": 4, "100% English": 5 }
MAP_ENJOY = { "Very boring": 1, "Rather boring": 2, "Neutral": 3, "Stimulating": 4, "Very stimulating": 5 }
MAP_SATISFACTION = { "Very disappointed": 1, "Disappointed": 2, "Neutral": 3, "Happy": 4, "Very happy": 5 }
MAP_PREP = { "Barely studied": 1, "Underprepared": 2, "Okay": 3, "Well prepared": 4, "Overprepared": 5 }

@dataclass
class UserProfile:
    first_name: str
    student_class: str
    user_key: str
    is_authenticated: bool = False
    is_teacher: bool = False

# ==========================================
# DEEL 2: DE SERVICE LAYER
# ==========================================

class CoreServices:
    def __init__(self) -> None:
        try:
            url: str = st.secrets["SUPABASE_URL"]
            key: str = st.secrets["SUPABASE_KEY"]
            self.db: Client = create_client(url, key)
            self.table_students = "students"
            self.table_logs = "pulse_logs"
            self.table_reflections = "eval_reflections"
            
            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
            self.ai_model = genai.GenerativeModel('gemini-1.5-flash')
        except KeyError as e:
            st.error(f"Systeemfout: Configuratie {e} ontbreekt in geheimen.")
            st.stop()

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def register_student(self, first_name: str, student_class: str, reg_code: str) -> bool:
        user_key = first_name.lower().strip()
        try:
            response = self.db.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) > 0: return False  
            new_student = { "user_key": user_key, "first_name": first_name, "class_name": student_class, "hashed_code": self._hash_password(reg_code) }
            self.db.table(self.table_students).insert(new_student).execute()
            return True
        except Exception: return False

    def login_student(self, first_name: str, reg_code: str) -> Optional[UserProfile]:
        user_key = first_name.lower().strip()
        try:
            response = self.db.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) == 0: return None  
            student_data = response.data[0]
            if student_data["hashed_code"] == self._hash_password(reg_code):
                is_teacher = (user_key == "johanj") 
                return UserProfile(first_name=student_data["first_name"], student_class=student_data["class_name"], user_key=user_key, is_authenticated=True, is_teacher=is_teacher)
            return None 
        except Exception: return None

    def log_pulse(self, user_key: str, class_name: str, scores: Dict[str, int]) -> bool:
        try:
            log_entry = {
                "user_key": user_key, "class_name": class_name,
                "participation": scores["participation"], "full_sentences": scores["full_sentences"],
                "exact_words": scores["exact_words"], "english_only": scores["english_only"], "lesson_enjoyment": scores["lesson_enjoyment"]
            }
            self.db.table(self.table_logs).insert(log_entry).execute()
            return True
        except Exception: return False

    def get_global_averages(self) -> List[float]:
        try:
            response = self.db.table(self.table_logs).select("*").execute()
            data = response.data
            if not data: return [3.0]*5
            n = len(data)
            return [
                sum(row["participation"] for row in data) / n,
                sum(row["full_sentences"] for row in data) / n,
                sum(row["exact_words"] for row in data) / n,
                sum(row["english_only"] for row in data) / n,
                sum(row["lesson_enjoyment"] for row in data) / n
            ]
        except Exception: return [3.0]*5

    def get_student_averages(self, user_key: str) -> List[float]:
        """Berekent het all-time gemiddelde van een specifieke leerling."""
        try:
            response = self.db.table(self.table_logs).select("*").eq("user_key", user_key).execute()
            data = response.data
            if not data: return [0.0]*5 # Geef 0 terug als er nog geen data is
            n = len(data)
            return [
                sum(row["participation"] for row in data) / n,
                sum(row["full_sentences"] for row in data) / n,
                sum(row["exact_words"] for row in data) / n,
                sum(row["english_only"] for row in data) / n,
                sum(row["lesson_enjoyment"] for row in data) / n
            ]
        except Exception: return [0.0]*5

    def log_reflection(self, data: Dict[str, Any]) -> bool:
        try:
            self.db.table(self.table_reflections).insert(data).execute()
            return True
        except Exception: return False

    def get_all_pulses(self) -> pd.DataFrame:
        try:
            res = self.db.table(self.table_logs).select("*").execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception: return pd.DataFrame()

    def get_all_reflections(self) -> pd.DataFrame:
        try:
            res = self.db.table(self.table_reflections).select("*").execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception: return pd.DataFrame()

    def generate_ai_summary(self, strengths: List[str], weaknesses: List[str]) -> str:
        if not strengths and not weaknesses: return "Geen data beschikbaar om te analyseren."
        prompt = f"""
        You are an expert educational AI assistant helping a language teacher named Johan. 
        Below is the raw feedback from students regarding a recent evaluation.
        STRENGTHS MENTIONED: {strengths}
        WEAKNESSES MENTIONED: {weaknesses}
        Provide a professional, insightful, and actionable summary for the teacher. 
        Highlight common themes. Structure with a short intro, bullet points for strengths, bullet points for areas of improvement, and a teaching tip.
        """
        try: return self.ai_model.generate_content(prompt).text
        except Exception as e: return f"⚠️ AI Summary failed. Check your API key. Error: {e}"

services = CoreServices()

# ==========================================
# DEEL 3A: STUDENT SCHERMEN
# ==========================================

def generate_smart_challenge(skill_name: str, score: int, avg: float) -> str:
    if skill_name == "English Only":
        if score >= 4: return "🌟 **English Only**: You already speak English almost all the time! **Challenge:** Before answering, pause for 2 seconds to structure your thoughts so your sentence becomes even more powerful."
        else: return "🚀 **English Only**: **Challenge:** Next lesson, try asking 'How do you say X in English?' instead of switching back to Dutch."
    elif skill_name == "Participation":
        if score >= 4: return "🌟 **Participation**: Great energy today! **Challenge:** Next time, try to encourage a quieter classmate to share their opinion too."
        else: return "🚀 **Participation**: **Challenge:** Set a small goal: raise your hand at least once, even if you are not 100% sure of the answer."
    elif skill_name == "Full Sentences":
        if score >= 4: return "🌟 **Full Sentences**: You communicate clearly. **Challenge:** Try to use advanced connecting words like 'however' or 'although' next time."
        else: return "🚀 **Full Sentences**: **Challenge:** Instead of giving 1-word answers, try to start your response by repeating part of the teacher's question."
    elif skill_name == "Exact Words":
        if score >= 4: return "🌟 **Exact Words**: Excellent vocabulary hunting! **Challenge:** Try to pick up one completely new expression from a classmate or the teacher next lesson."
        else: return "🚀 **Exact Words**: **Challenge:** When you can't find a word, try to describe it in English (e.g., 'the thing you use to...') instead of giving up."
    return ""

def render_radar_chart(student_recent: List[int], student_avg: List[float], global_avg: List[float]) -> None:
    categories = ['Participation', 'Full Sentences', 'Exact Words', 'English Only', 'Enjoyment']
    closed_cat = categories + [categories[0]]
    
    # Sluit alle 3 de lijnen
    closed_recent = student_recent + [student_recent[0]]
    closed_avg = student_avg + [student_avg[0]]
    closed_glob = global_avg + [global_avg[0]]
    
    fig_radar = go.Figure()
    
    # Lijn 1: Schoolgemiddelde (Grijs)
    fig_radar.add_trace(go.Scatterpolar(
        r=closed_glob, theta=closed_cat, fill='toself', name='School Average',
        line_color='rgba(150, 150, 150, 0.5)', fillcolor='rgba(200, 200, 200, 0.2)', line_shape='spline', line_width=2
    ))
    
    # Lijn 2: Persoonlijk All-time Gemiddelde (Donkerder blauw, stippellijn, niet gevuld)
    # Check of ze al een gemiddelde hebben, anders heeft deze lijn geen zin
    if any(val > 0 for val in student_avg):
        fig_radar.add_trace(go.Scatterpolar(
            r=closed_avg, theta=closed_cat, fill='none', name='Your All-Time Avg',
            line_color='#2c5c91', line_dash='dash', line_shape='spline', line_width=3
        ))
        
    # Lijn 3: Score van Vandaag (Helder blauw, gevuld)
    fig_radar.add_trace(go.Scatterpolar(
        r=closed_recent, theta=closed_cat, fill='toself', name='Today\'s Score',
        line_color='#4A90E2', fillcolor='rgba(74, 144, 226, 0.3)', line_shape='spline', line_width=4
    ))
    
    fig_radar.update_layout(
        template="plotly_white",
        polar=dict(radialaxis=dict(visible=True, range=[0, 5], gridcolor='#e5e5e5'), angularaxis=dict(gridcolor='#e5e5e5', tickfont=dict(size=13, color='#333', weight='bold'))),
        showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=60, r=60, t=40, b=40)
    )
    st.plotly_chart(fig_radar, use_container_width=True)

def render_student_dashboard() -> None:
    user = st.session_state.current_user
    safe_user_key = getattr(user, 'user_key', user.first_name.lower().strip())
    
    col1, col2 = st.columns([8, 1])
    with col1: st.markdown(f"<h2>Sup <span style='color: #4A90E2;'>{user.first_name}</span>! 👋</h2>", unsafe_allow_html=True)
    with col2:
        if st.button("Logout"):
            st.session_state.current_user = UserProfile(first_name="", student_class="", user_key="")
            st.session_state.recent_scores = None
            st.rerun()
            
    st.write("---")
    tab_pulse, tab_reflection = st.tabs(["🔥 Pulse Check", "📝 Evaluation Reflection"])
    
    with tab_pulse:
        col_form, col_space, col_charts = st.columns([1.2, 0.1, 1.5]) 
        with col_form:
            st.markdown("### Weekly Pulse")
            with st.form("pulse_form"):
                q1 = st.select_slider("1. How active were you in class today?", options=list(MAP_ACTIVITY.keys()))
                q2 = st.select_slider("2. Did you try to answer in full sentences?", options=list(MAP_FREQ.keys()))
                q3 = st.select_slider("3. Did you search for the EXACT right words?", options=list(MAP_FREQ.keys()))
                q4 = st.select_slider("4. Did you speak English the entire time?", options=list(MAP_ENG.keys()))
                q5 = st.select_slider("5. How stimulating was today's lesson?", options=list(MAP_ENJOY.keys()))
                
                if st.form_submit_button("🚀 Submit & Earn XP"):
                    scores_dict = {
                        "participation": MAP_ACTIVITY[q1], "full_sentences": MAP_FREQ[q2],
                        "exact_words": MAP_FREQ[q3], "english_only": MAP_ENG[q4], "lesson_enjoyment": MAP_ENJOY[q5]
                    }
                    if services.log_pulse(safe_user_key, user.student_class, scores_dict):
                        st.success("Awesome! Data logged and XP earned! 🎯")
                        st.session_state.recent_scores = scores_dict
                        st.rerun()

        with col_charts:
            if st.session_state.recent_scores:
                scores = st.session_state.recent_scores
                student_recent_array = [scores["participation"], scores["full_sentences"], scores["exact_words"], scores["english_only"], scores["lesson_enjoyment"]]
                
                # Haal beide gemiddeldes op
                global_averages = services.get_global_averages()
                student_averages = services.get_student_averages(safe_user_key)
                
                st.markdown("### Your Growth Radar")
                render_radar_chart(student_recent_array, student_averages, global_averages)
                
                st.markdown("### AI Coach Feedback")
                st.info(generate_smart_challenge("Participation", scores["participation"], global_averages[0]))
                st.info(generate_smart_challenge("Full Sentences", scores["full_sentences"], global_averages[1]))
                st.info(generate_smart_challenge("Exact Words", scores["exact_words"], global_averages[2]))
                st.info(generate_smart_challenge("English Only", scores["english_only"], global_averages[3]))
            else:
                st.info("👈 Fill in your Pulse Check on the left to unlock your Radar and personalized feedback!")

    with tab_reflection:
        st.markdown("### Reflect on your recent evaluation")
        with st.form("reflection_form"):
            colA, colB = st.columns(2)
            with colA: eval_skill = st.selectbox("Which skill was evaluated?", SKILLS)
            with colB: eval_unit = st.selectbox("Which unit?", UNITS)
            st.write("---")
            q_sat = st.select_slider("How satisfied are you with your grade?", options=list(MAP_SATISFACTION.keys()))
            q_prep = st.select_slider("How well did you prepare for this?", options=list(MAP_PREP.keys()))
            st.write("---")
            text_strengths = st.text_area("What went well? (Strengths) 💪", placeholder="e.g., I knew all the vocabulary...")
            text_weaknesses = st.text_area("What needs improvement? (Weaknesses) 🎯", placeholder="e.g., I struggled with grammar rules...")
            
            if st.form_submit_button("💾 Save Reflection"):
                if text_strengths and text_weaknesses:
                    data = {
                        "user_key": safe_user_key, "class_name": user.student_class,
                        "skill": eval_skill, "unit": eval_unit,
                        "satisfaction": MAP_SATISFACTION[q_sat], "preparation": MAP_PREP[q_prep],
                        "strengths": text_strengths, "weaknesses": text_weaknesses
                    }
                    if services.log_reflection(data): st.success("Reflection securely saved to your portfolio!")
                else: st.warning("Please fill in both your strengths and weaknesses.")

# ==========================================
# DEEL 3B: TEACHER DASHBOARD (RBAC & AI)
# ==========================================

def render_teacher_dashboard() -> None:
    st.markdown("<h2>🎓 Teacher Analytics: <span style='color: #4A90E2;'>Admin Panel</span></h2>", unsafe_allow_html=True)
    if st.button("Logout"):
        st.session_state.current_user = UserProfile(first_name="", student_class="", user_key="")
        st.rerun()
    st.write("---")
    
    tab_analytics, tab_reflections = st.tabs(["📊 Pulse Analytics", "🧠 AI Reflection Insights"])
    
    with tab_analytics:
        st.markdown("### Top & Bottom Performers")
        df_pulse = services.get_all_pulses()
        if not df_pulse.empty:
            col_f1, col_f2 = st.columns(2)
            with col_f1: filter_class = st.selectbox("Filter by Class", ["All"] + CLASSES)
            with col_f2:
                metrics = ["participation", "full_sentences", "exact_words", "english_only", "lesson_enjoyment"]
                target_metric = st.selectbox("Select Metric to analyze", metrics)
                
            if filter_class != "All": df_pulse = df_pulse[df_pulse['class_name'] == filter_class]
                
            if not df_pulse.empty:
                avg_scores = df_pulse.groupby('user_key')[target_metric].mean().reset_index()
                avg_scores = avg_scores.sort_values(by=target_metric, ascending=False)
                
                colA, colB = st.columns(2)
                with colA:
                    st.success(f"🏆 Highest Scoring ({target_metric})")
                    st.dataframe(avg_scores.head(5), hide_index=True)
                with colB:
                    st.error(f"⚠️ Needs Attention ({target_metric})")
                    st.dataframe(avg_scores.tail(5), hide_index=True)
            else: st.info("No data for this class yet.")
        else: st.info("No pulse data available in the database.")

    with tab_reflections:
        st.markdown("### Class Evaluation Overview")
        df_ref = services.get_all_reflections()
        if not df_ref.empty:
            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1: ref_class = st.selectbox("Class", CLASSES, key="r_class")
            with col_r2: ref_unit = st.selectbox("Unit", UNITS, key="r_unit")
            with col_r3: ref_skill = st.selectbox("Skill", SKILLS, key="r_skill")
            
            mask = (df_ref['class_name'] == ref_class) & (df_ref['unit'] == ref_unit) & (df_ref['skill'] == ref_skill)
            filtered_ref = df_ref[mask]
            
            if not filtered_ref.empty:
                st.write("---")
                all_str = filtered_ref['strengths'].dropna().tolist()
                all_weak = filtered_ref['weaknesses'].dropna().tolist()
                
                st.markdown("#### 🤖 Gemini AI Executive Summary")
                with st.spinner("Analyzing student feedback with Google Gemini..."):
                    ai_summary = services.generate_ai_summary(all_str, all_weak)
                st.markdown(f"<div style='background-color: #e8f4fd; padding: 20px; border-radius: 10px; border-left: 5px solid #4A90E2;'>{ai_summary}</div>", unsafe_allow_html=True)
                
                st.write("---")
                st.markdown(f"**Individual Student Feedback ({len(filtered_ref)} logs)**")
                for index, row in filtered_ref.iterrows():
                    st.markdown(f"""
                    <div class='teacher-card'>
                        <strong>Student:</strong> {str(row['user_key']).capitalize()} <br>
                        <strong>Satisfaction:</strong> {row['satisfaction']}/5 | <strong>Preparation:</strong> {row['preparation']}/5 <br><br>
                        <strong>💪 Strengths:</strong> {row['strengths']} <br>
                        <strong>🎯 Weaknesses:</strong> {row['weaknesses']}
                    </div>
                    """, unsafe_allow_html=True)
            else: st.info(f"No reflections found for {ref_class} - {ref_unit} - {ref_skill}.")
        else: st.info("No reflections available in the database yet.")

# ==========================================
# DEEL 4: DE MOTOR
# ==========================================

def init_session() -> None:
    if 'current_user' not in st.session_state: st.session_state.current_user = UserProfile(first_name="", student_class="", user_key="")
    if 'recent_scores' not in st.session_state: st.session_state.recent_scores = None

def render_auth_screen() -> None:
    st.markdown("<h1 style='text-align: center; color: #4A90E2;'>⚡ vvXP Tracker</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #666;'>Track your progress, earn XP and level up your English.</p>", unsafe_allow_html=True)
    st.write("---")
    
    col_space1, col_main, col_space2 = st.columns([1, 2, 1])
    with col_main:
        tab_login, tab_register = st.tabs(["🔐 Login", "📝 Register"])
        with tab_login:
            with st.form("login_form"):
                login_name = st.text_input("First Name")
                login_code = st.text_input("Registration Code", type="password")
                if st.form_submit_button("Enter vvXP Tracker"):
                    user_profile = services.login_student(login_name, login_code)
                    if user_profile:
                        st.session_state.current_user = user_profile
                        st.rerun() 
                    else: st.error("Oops! Wrong name or code.")
        with tab_register:
            with st.form("register_form"):
                new_name = st.text_input("First Name")
                new_class = st.selectbox("Class", CLASSES)
                new_code = st.text_input("Create Code", type="password")
                if st.form_submit_button("Register"):
                    if services.register_student(new_name, new_class, new_code): st.success("Success! Please Login.")
                    else: st.error("Name taken or system error.")

def main() -> None:
    init_session()
    user = st.session_state.current_user
    if not user.is_authenticated: render_auth_screen()
    else:
        if user.is_teacher: render_teacher_dashboard()
        else: render_student_dashboard()

if __name__ == "__main__":
    main()
