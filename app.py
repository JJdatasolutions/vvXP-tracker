import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple

from supabase import create_client, Client
import google.generativeai as genai

# ==========================================
# DEEL 1: CONFIGURATIE, MODELLEN & GAMIFICATION
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
    div[data-testid="stForm"], .teacher-card, .dashboard-card {
        background-color: #ffffff; border-radius: 12px; padding: 2rem;
        border: 1px solid #e1e4e8; box-shadow: 0 4px 15px rgba(0,0,0,0.04);
        margin-bottom: 1rem;
    }
    .badge-locked { filter: grayscale(100%); opacity: 0.4; text-align: center; }
    .badge-unlocked { text-align: center; transform: scale(1.05); transition: 0.2s; }
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

# --- GAMIFICATION CONSTANTS ---
LEVELS = [
    {"level": 1, "title": "Beginner 🥚", "xp_req": 0},
    {"level": 2, "title": "Novice 🌱", "xp_req": 200},
    {"level": 3, "title": "Explorer 🧭", "xp_req": 500},
    {"level": 4, "title": "Apprentice 🛠️", "xp_req": 1000},
    {"level": 5, "title": "Fluent Apprentice 🗣️", "xp_req": 1800},
    {"level": 6, "title": "Wordsmith ✍️", "xp_req": 2800},
    {"level": 7, "title": "Master 🎓", "xp_req": 4000},
    {"level": 8, "title": "Native Master 👑", "xp_req": 6000}
]

BADGE_DICT = {
    "chatterbox": {"name": "The Chatterbox", "emoji": "🗣️", "desc": "Score 5 on Participation 3 times."},
    "oxford": {"name": "Oxford Dictionary", "emoji": "📖", "desc": "Score 5 on Exact Words."},
    "brit": {"name": "The Brit", "emoji": "🇬🇧", "desc": "Score 5 on English Only."}
}

@dataclass
class UserProfile:
    first_name: str
    student_class: str
    user_key: str
    is_authenticated: bool = False
    is_teacher: bool = False
    total_xp: int = 0
    current_streak: int = 0
    last_pulse_date: Optional[str] = None
    unlocked_badges: List[str] = field(default_factory=list)

def calculate_level_stats(xp: int) -> Tuple[int, str, int, int, float]:
    """Returns: current_level, title, current_level_xp_base, next_level_xp_req, progress_percentage"""
    current_level, title, base_xp, next_xp = 1, LEVELS[0]["title"], 0, LEVELS[1]["xp_req"]
    for i, lvl in enumerate(LEVELS):
        if xp >= lvl["xp_req"]:
            current_level = lvl["level"]
            title = lvl["title"]
            base_xp = lvl["xp_req"]
            next_xp = LEVELS[i+1]["xp_req"] if i + 1 < len(LEVELS) else lvl["xp_req"]
    
    if next_xp == base_xp: 
        progress = 1.0 # Max level
    else:
        progress = (xp - base_xp) / (next_xp - base_xp)
    return current_level, title, base_xp, next_xp, min(max(progress, 0.0), 1.0)


# ==========================================
# DEEL 2: DE SERVICE LAYER (De Keuken)
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
            new_student = { 
                "user_key": user_key, "first_name": first_name, "class_name": student_class, 
                "hashed_code": self._hash_password(reg_code),
                "total_xp": 0, "current_streak": 0, "unlocked_badges": []
            }
            self.db.table(self.table_students).insert(new_student).execute()
            return True
        except Exception: 
            return False

    def login_student(self, first_name: str, reg_code: str) -> Optional[UserProfile]:
        user_key = first_name.lower().strip()
        try:
            response = self.db.table(self.table_students).select("*").eq("user_key", user_key).execute()
            if len(response.data) == 0: return None  
            s_data = response.data[0]
            if s_data["hashed_code"] == self._hash_password(reg_code):
                is_teacher = (user_key == "johanj") 
                badges = s_data.get("unlocked_badges", [])
                if isinstance(badges, str): badges = []
                
                return UserProfile(
                    first_name=s_data["first_name"], student_class=s_data["class_name"], 
                    user_key=user_key, is_authenticated=True, is_teacher=is_teacher,
                    total_xp=s_data.get("total_xp", 0), current_streak=s_data.get("current_streak", 0),
                    last_pulse_date=s_data.get("last_pulse_date"), unlocked_badges=badges
                )
            return None 
        except Exception as e: 
            print(f"Login error: {e}")
            return None

    def get_student_pulses(self, user_key: str) -> pd.DataFrame:
        try:
            res = self.db.table(self.table_logs).select("*").eq("user_key", user_key).execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception: 
            return pd.DataFrame()

    def process_gamification_pulse(self, user: UserProfile, scores: Dict[str, int]) -> Dict[str, Any]:
        today = datetime.now().date()
        streak = user.current_streak
        
        # 1. Streak Logic
        if user.last_pulse_date:
            last_date = datetime.strptime(user.last_pulse_date, "%Y-%m-%d").date()
            days_diff = (today - last_date).days
            if days_diff <= 10:  
                if days_diff > 0: streak += 1 
            else:
                streak = 1 
        else:
            streak = 1
            
        # 2. XP Calculation
        base_xp = sum(scores.values()) * 10
        multiplier = 1.2 if streak >= 3 else 1.0
        earned_xp = int(base_xp * multiplier)
        new_total_xp = user.total_xp + earned_xp
        
        # 3. Badge Logic
        badges = list(user.unlocked_badges)
        newly_unlocked = []
        
        if "oxford" not in badges and scores["exact_words"] == 5:
            badges.append("oxford"); newly_unlocked.append("oxford")
        if "brit" not in badges and scores["english_only"] == 5:
            badges.append("brit"); newly_unlocked.append("brit")
            
        if "chatterbox" not in badges:
            df_past = self.get_student_pulses(user.user_key)
            past_5s = len(df_past[df_past['participation'] == 5]) if not df_past.empty else 0
            if (past_5s + (1 if scores["participation"] == 5 else 0)) >= 3:
                badges.append("chatterbox"); newly_unlocked.append("chatterbox")

        # 4. Check Level Up
        old_lvl, _, _, _, _ = calculate_level_stats(user.total_xp)
        new_lvl, _, _, _, _ = calculate_level_stats(new_total_xp)
        leveled_up = new_lvl > old_lvl

        # 5. Database Update
        try:
            self.db.table(self.table_students).update({
                "total_xp": new_total_xp, "current_streak": streak, 
                "last_pulse_date": today.strftime("%Y-%m-%d"), "unlocked_badges": badges
            }).eq("user_key", user.user_key).execute()
        except Exception as e:
            print(f"Error updating gamification state: {e}")

        return {
            "earned_xp": earned_xp, "new_total_xp": new_total_xp, "new_streak": streak,
            "new_badges": badges, "newly_unlocked": newly_unlocked, 
            "leveled_up": leveled_up, "streak_milestone": streak > 0 and streak % 5 == 0,
            "multiplier": multiplier
        }

    def log_pulse(self, user: UserProfile, scores: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            log_entry = {
                "user_key": user.user_key, "class_name": user.student_class,
                "participation": scores["participation"], "full_sentences": scores["full_sentences"],
                "exact_words": scores["exact_words"], "english_only": scores["english_only"], "lesson_enjoyment": scores["lesson_enjoyment"]
            }
            self.db.table(self.table_logs).insert(log_entry).execute()
            return self.process_gamification_pulse(user, scores)
        except Exception as e: 
            print(f"Error logging pulse: {e}")
            return None

    def get_global_averages(self) -> List[float]:
        try:
            response = self.db.table(self.table_logs).select("*").execute()
            data = response.data
            if not data: return [3.0]*5
            n = len(data)
            return [
                sum(row["participation"] for row in data) / n, sum(row["full_sentences"] for row in data) / n,
                sum(row["exact_words"] for row in data) / n, sum(row["english_only"] for row in data) / n, sum(row["lesson_enjoyment"] for row in data) / n
            ]
        except Exception: return [3.0]*5

    def get_student_averages(self, user_key: str) -> List[float]:
        df = self.get_student_pulses(user_key)
        if df.empty: return [0.0]*5
        return df[['participation', 'full_sentences', 'exact_words', 'english_only', 'lesson_enjoyment']].mean().tolist()

    def get_student_percentiles(self, current_scores: Dict[str, int]) -> Dict[str, float]:
        try:
            response = self.db.table(self.table_logs).select("*").execute()
            df_all = pd.DataFrame(response.data)
            if df_all.empty: return {k: 0.0 for k in current_scores.keys()}
            percentiles = {}
            for key in current_scores.keys():
                percentile = ((df_all[key] <= current_scores[key]).sum() / len(df_all)) * 100
                percentiles[key] = round(percentile, 0)
            return percentiles
        except Exception: return {}

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

    def get_all_students(self) -> pd.DataFrame:
        try:
            res = self.db.table(self.table_students).select("*").execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e: 
            print(f"Error fetching students: {e}")
            return pd.DataFrame()

    def get_all_reflections(self) -> pd.DataFrame:
        try:
            res = self.db.table(self.table_reflections).select("*").execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception: return pd.DataFrame()

    def generate_ai_summary(self, strengths: List[str], weaknesses: List[str]) -> str:
        if not strengths and not weaknesses: return "Geen data beschikbaar om te analyseren."
        prompt = f"You are an expert educational AI. Raw feedback STRENGTHS: {strengths} WEAKNESSES: {weaknesses}. Provide a professional summary highlighting themes, strengths, improvements, and a teaching tip."
        try: return self.ai_model.generate_content(prompt).text
        except Exception as e: return f"⚠️ AI Summary failed. Error: {e}"

services = CoreServices()

# ==========================================
# DEEL 3A: STUDENT SCHERMEN (De Bediening voor Leerlingen)
# ==========================================

def render_radar_chart(student_recent: List[int], student_avg: List[float], global_avg: List[float]) -> None:
    categories = ['Participation', 'Full Sentences', 'Exact Words', 'English Only', 'Enjoyment']
    closed_cat = categories + [categories[0]]
    closed_recent, closed_avg, closed_glob = student_recent + [student_recent[0]], student_avg + [student_avg[0]], global_avg + [global_avg[0]]
    
    fig_radar = go.Figure()
    fig_radar.add_trace(go.Scatterpolar(r=closed_glob, theta=closed_cat, fill='toself', name='School Average', line_color='rgba(150, 150, 150, 0.5)', fillcolor='rgba(200, 200, 200, 0.2)'))
    if any(val > 0 for val in student_avg):
        fig_radar.add_trace(go.Scatterpolar(r=closed_avg, theta=closed_cat, fill='none', name='Your All-Time Avg', line_color='#2c5c91', line_dash='dash'))
    fig_radar.add_trace(go.Scatterpolar(r=closed_recent, theta=closed_cat, fill='toself', name='Today\'s Score', line_color='#4A90E2', fillcolor='rgba(74, 144, 226, 0.3)', line_width=3))
    fig_radar.update_layout(template="plotly_white", polar=dict(radialaxis=dict(visible=True, range=[0, 5])), showlegend=True, legend=dict(orientation="h", y=-0.3), margin=dict(l=40, r=40, t=20, b=20))
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

    lvl, lvl_title, base_xp, next_xp, prog_pct = calculate_level_stats(user.total_xp)
    
    st.markdown("<div class='dashboard-card'>", unsafe_allow_html=True)
    c_level, c_xp, c_streak = st.columns([2, 3, 1])
    with c_level:
        st.markdown(f"### Lvl {lvl}: {lvl_title}")
    with c_xp:
        st.markdown(f"**XP:** {user.total_xp} / {next_xp}")
        st.progress(prog_pct)
    with c_streak:
        st.markdown(f"<h3 style='text-align: center;'>🔥 {user.current_streak}</h3>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #666; font-size: 0.8em; margin-top: -10px;'>Week Streak</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    tab_pulse, tab_reflection = st.tabs(["🔥 Pulse Check", "📝 Evaluation Reflection"])
    
    with tab_pulse:
        col_form, col_charts = st.columns([1.2, 1.5], gap="large") 
        with col_form:
            st.markdown("### Weekly Pulse")
            with st.form("pulse_form"):
                q1 = st.select_slider("1. How active were you in class today?", options=list(MAP_ACTIVITY.keys()))
                q2 = st.select_slider("2. Did you try to answer in full sentences?", options=list(MAP_FREQ.keys()))
                q3 = st.select_slider("3. Did you search for the EXACT right words?", options=list(MAP_FREQ.keys()))
                q4 = st.select_slider("4. Did you speak English the entire time?", options=list(MAP_ENG.keys()))
                q5 = st.select_slider("5. How stimulating was today's lesson?", options=list(MAP_ENJOY.keys()))
                
                if st.form_submit_button("🚀 Submit & Earn XP"):
                    scores_dict = {"participation": MAP_ACTIVITY[q1], "full_sentences": MAP_FREQ[q2], "exact_words": MAP_FREQ[q3], "english_only": MAP_ENG[q4], "lesson_enjoyment": MAP_ENJOY[q5]}
                    
                    game_results = services.log_pulse(user, scores_dict)
                    if game_results:
                        user.total_xp = game_results["new_total_xp"]
                        user.current_streak = game_results["new_streak"]
                        user.unlocked_badges = game_results["new_badges"]
                        st.session_state.recent_scores = scores_dict
                        
                        st.success(f"Awesome! You earned +{game_results['earned_xp']} XP! 🎯 " + (f"(Includes {game_results['multiplier']}x Streak Bonus!)" if game_results['multiplier'] > 1.0 else ""))
                        
                        if game_results["leveled_up"]:
                            st.balloons()
                            st.toast("🎉 LEVEL UP! You reached a new rank!", icon="🌟")
                        if game_results["streak_milestone"]:
                            st.snow()
                            st.toast(f"🔥 INCREDIBLE! {user.current_streak} Week Streak!", icon="🔥")
                        for badge in game_results["newly_unlocked"]:
                            st.toast(f"🏆 NEW BADGE: {BADGE_DICT[badge]['name']}!", icon=BADGE_DICT[badge]['emoji'])
                        
                        st.rerun()

            st.markdown("### 🏆 Achievement Cabinet")
            b_cols = st.columns(3)
            for i, (b_key, b_info) in enumerate(BADGE_DICT.items()):
                has_badge = b_key in user.unlocked_badges
                css_class = "badge-unlocked" if has_badge else "badge-locked"
                with b_cols[i % 3]:
                    st.markdown(f"<div class='{css_class}'><h1>{b_info['emoji']}</h1><strong>{b_info['name']}</strong><br><small>{b_info['desc']}</small></div>", unsafe_allow_html=True)

        with col_charts:
            if st.session_state.recent_scores:
                scores = st.session_state.recent_scores
                student_recent_array = [scores["participation"], scores["full_sentences"], scores["exact_words"], scores["english_only"], scores["lesson_enjoyment"]]
                
                global_averages = services.get_global_averages()
                student_averages = services.get_student_averages(safe_user_key)
                
                st.markdown("### Your Growth Radar")
                render_radar_chart(student_recent_array, student_averages, global_averages)

                st.markdown("### AI Coach Feedback")
                st.info(f"🌟 **English Only**: Your score was {scores['english_only']}/5. Keep striving for 100% immersion!")
            else:
                st.info("👈 Fill in your Pulse Check on the left to unlock your Radar, earn XP, and level up!")

    with tab_reflection:
        st.markdown("### Reflect on your recent evaluation")
        with st.form("reflection_form"):
            colA, colB = st.columns(2)
            with colA: eval_skill = st.selectbox("Which skill was evaluated?", SKILLS)
            with colB: eval_unit = st.selectbox("Which unit?", UNITS)
            q_sat = st.select_slider("How satisfied are you with your grade?", options=list(MAP_SATISFACTION.keys()))
            q_prep = st.select_slider("How well did you prepare for this?", options=list(MAP_PREP.keys()))
            text_strengths = st.text_area("What went well? (Strengths) 💪")
            text_weaknesses = st.text_area("What needs improvement? (Weaknesses) 🎯")
            
            if st.form_submit_button("💾 Save Reflection"):
                if text_strengths and text_weaknesses:
                    data = { "user_key": safe_user_key, "class_name": user.student_class, "skill": eval_skill, "unit": eval_unit, "satisfaction": MAP_SATISFACTION[q_sat], "preparation": MAP_PREP[q_prep], "strengths": text_strengths, "weaknesses": text_weaknesses }
                    if services.log_reflection(data): st.success("Reflection securely saved to your portfolio!")

# ==========================================
# DEEL 3B: TEACHER DASHBOARD (De Bediening voor Leraren)
# ==========================================

def render_teacher_radar_chart(df_pulse: pd.DataFrame, selected_classes: List[str]) -> None:
    categories = ['participation', 'full_sentences', 'exact_words', 'english_only', 'lesson_enjoyment']
    display_cat = ['Participation', 'Full Sentences', 'Exact Words', 'English Only', 'Enjoyment', 'Participation']
    
    fig_radar = go.Figure()
    
    global_avg = df_pulse[categories].mean().tolist()
    global_avg += [global_avg[0]] 
    fig_radar.add_trace(go.Scatterpolar(
        r=global_avg, theta=display_cat, fill='toself', name='Global Average',
        line_color='rgba(150, 150, 150, 0.5)', fillcolor='rgba(200, 200, 200, 0.2)'
    ))
    
    colors = ['#4A90E2', '#E24A4A', '#50E3C2', '#F5A623', '#9013FE']
    for i, cls in enumerate(selected_classes):
        cls_data = df_pulse[df_pulse['class_name'] == cls]
        if not cls_data.empty:
            cls_avg = cls_data[categories].mean().tolist()
            cls_avg += [cls_avg[0]]
            fig_radar.add_trace(go.Scatterpolar(
                r=cls_avg, theta=display_cat, fill='toself', name=f'{cls}',
                line_color=colors[i % len(colors)], opacity=0.7
            ))
            
    fig_radar.update_layout(
        template="plotly_white",
        polar=dict(radialaxis=dict(visible=True, range=[0, 5])),
        showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
        margin=dict(l=40, r=40, t=40, b=40)
    )
    st.plotly_chart(fig_radar, use_container_width=True)

def render_teacher_dashboard() -> None:
    st.markdown("<h2>🎓 Teacher Analytics: <span style='color: #4A90E2;'>Admin Panel</span></h2>", unsafe_allow_html=True)
    if st.button("Logout"):
        st.session_state.current_user = UserProfile(first_name="", student_class="", user_key="")
        st.rerun()
    st.write("---")
    
    df_pulse = services.get_all_pulses()
    df_students = services.get_all_students()
    
    if df_pulse.empty:
        st.warning("No pulse data available yet. Let the students log some XP first!")
        return

    metrics_map = {
        "Participation": "participation", 
        "Full Sentences": "full_sentences", 
        "Exact Words": "exact_words", 
        "English Only": "english_only", 
        "Enjoyment": "lesson_enjoyment"
    }
    
    tab_compare, tab_trends, tab_leaderboards = st.tabs(["📊 Class Comparisons", "📈 Trends Over Time", "🏆 Leaderboards & Extremes"])
    
    # --- TAB 1: RADAR CHART ---
    with tab_compare:
        st.markdown("### Compare Class Averages")
        st.write("Select two or more classes to compare their performance against the global average.")
        
        available_classes = df_pulse['class_name'].unique().tolist()
        selected_classes = st.multiselect("Select Classes", available_classes, default=available_classes[:2] if len(available_classes) >= 2 else available_classes)
        
        col_radar_space1, col_radar, col_radar_space2 = st.columns([1, 2, 1])
        with col_radar:
            if selected_classes:
                render_teacher_radar_chart(df_pulse, selected_classes)
            else:
                st.info("Please select at least one class to display the radar chart.")

    # --- TAB 2: TIME-SERIES ---
    with tab_trends:
        st.markdown("### Performance Trends Over Time")
        
        if 'created_at' in df_pulse.columns:
            df_pulse['date'] = pd.to_datetime(df_pulse['created_at']).dt.date
            
            selected_metrics = st.multiselect("Select Dimensions to Track", list(metrics_map.keys()), default=["Participation", "English Only"])
            
            if selected_metrics:
                db_metrics = [metrics_map[m] for m in selected_metrics]
                trend_df = df_pulse.groupby('date')[db_metrics].mean().reset_index()
                
                trend_melted = trend_df.melt(id_vars=['date'], value_vars=db_metrics, var_name='Metric', value_name='Average Score')
                trend_melted['Metric'] = trend_melted['Metric'].map({v: k for k, v in metrics_map.items()})
                
                fig_line = px.line(trend_melted, x='date', y='Average Score', color='Metric', markers=True, 
                                   range_y=[0, 5.2], template='plotly_white')
                fig_line.update_layout(xaxis_title="Date", yaxis_title="Average Score (Out of 5)")
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info("Select at least one dimension to view the trend.")
        else:
            st.warning("⚠️ No 'created_at' column found in pulse_logs. Time tracking is not possible without timestamps.")

    # --- TAB 3: LEADERBOARDS ---
    with tab_leaderboards:
        st.markdown("### Gamification Top 10")
        
        if not df_students.empty:
            col_xp, col_streak = st.columns(2)
            
            with col_xp:
                st.markdown("#### 🌟 Top 10 XP Earners")
                top_xp = df_students[['first_name', 'class_name', 'total_xp']].sort_values(by='total_xp', ascending=False).head(10)
                top_xp.index = range(1, len(top_xp) + 1)
                st.dataframe(top_xp, use_container_width=True)
                
            with col_streak:
                st.markdown("#### 🔥 Top 10 Longest Streaks")
                top_streak = df_students[['first_name', 'class_name', 'current_streak']].sort_values(by='current_streak', ascending=False).head(10)
                top_streak.index = range(1, len(top_streak) + 1)
                st.dataframe(top_streak, use_container_width=True)
        else:
            st.info("No student profiles available for leaderboards.")
            
        st.write("---")
        st.markdown("### Top & Bottom 5 per Dimension")
        target_dim = st.selectbox("Select Dimension to Analyze", list(metrics_map.keys()))
        db_dim = metrics_map[target_dim]
        
        student_dim_avg = df_pulse.groupby('user_key')[db_dim].mean().reset_index()
        
        if not df_students.empty:
            merged_stats = pd.merge(student_dim_avg, df_students[['user_key', 'first_name', 'class_name']], on='user_key')
        else:
            merged_stats = student_dim_avg
            merged_stats['first_name'] = merged_stats['user_key']
            merged_stats['class_name'] = "Unknown"
            
        merged_stats = merged_stats.sort_values(by=db_dim, ascending=False)
        merged_stats[db_dim] = merged_stats[db_dim].round(2)
        
        col_top, col_bot = st.columns(2)
        with col_top:
            st.success(f"🏆 Top 5 - Highest Average in {target_dim}")
            top_5 = merged_stats[['first_name', 'class_name', db_dim]].head(5)
            top_5.index = range(1, len(top_5) + 1)
            st.dataframe(top_5, use_container_width=True)
            
        with col_bot:
            st.error(f"⚠️ Bottom 5 - Needs attention in {target_dim}")
            bottom_5 = merged_stats[['first_name', 'class_name', db_dim]].tail(5).sort_values(by=db_dim, ascending=True)
            bottom_5.index = range(1, len(bottom_5) + 1)
            st.dataframe(bottom_5, use_container_width=True)

# ==========================================
# DEEL 4: DE MOTOR (Opstarten van de applicatie)
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
    if not user.is_authenticated: 
        render_auth_screen()
    else:
        if user.is_teacher: render_teacher_dashboard()
        else: render_student_dashboard()

if __name__ == "__main__":
    main()
