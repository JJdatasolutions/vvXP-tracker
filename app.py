import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

# Supabase import (zorg dat je 'pip install supabase' hebt gedraaid)
from supabase import create_client, Client

# ==========================================
# DEEL 1: CONFIGURATIE & MODELLEN (De Fundering)
# ==========================================

# 1. Pagina configuratie (Moet ALTIJD als allereerste Streamlit commando!)
st.set_page_config(page_title="vvXP Tracker", page_icon="⚡", layout="wide")

# Custom CSS voor een strakke, moderne look
st.markdown("""
    <style>
    .stButton>button { border-radius: 20px; font-weight: bold; }
    .stProgress .st-bo { background-color: #00f2fe; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Vaste gegevens (Constants)
CLASSES: List[str] = ["5HW", "5ECWI", "5ECMT", "5MT", "5WEMT", "5WEWI", "5WEWIC", "6ECMT", "6MT", "6WEWI", "6ECWI", "6HW"]
CLASS_AVG_SKILLS: Dict[str, float] = {
    'Participation': 3.2, 
    'Full Sentences': 3.8, 
    'Vocab Care': 2.9, 
    'Content Thought': 3.5, 
    'Written Care': 3.1
}

@dataclass
class StudentProfile:
    """Het digitale paspoort van de student. Dit reist mee in het geheugen van de browser."""
    first_name: str
    student_class: str
    is_authenticated: bool = False

# ==========================================
# DEEL 2: DE BUTLER (Supabase Service Layer)
# ==========================================

class SupabaseButler:
    """
    Regelt alle veilige communicatie met de Supabase database.
    Verbergt de complexe database-logica voor de rest van de applicatie.
    """
    
    def __init__(self) -> None:
        """Initialiseert de verbinding met het database-kluizenstelsel."""
        try:
            # Standaard complexiteit voor het ophalen van geheimen: \mathcal{O}(1)
            url: str = st.secrets["SUPABASE_URL"]
            key: str = st.secrets["SUPABASE_KEY"]
            self.client: Client = create_client(url, key)
            self.table_name: str = "students"
        except KeyError as e:
            st.error(f"Systeemfout: Configuratie {e} ontbreekt in .streamlit/secrets.toml")
            # We stoppen het script veilig als de sleutels er niet zijn
            st.stop()

    def _hash_password(self, password: str) -> str:
        """Maakt het wachtwoord onleesbaar voor veiligheid in de database."""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def register_student(self, first_name: str, student_class: str, reg_code: str) -> bool:
        """Slaat de nieuwe student op in Supabase. Geeft True als het lukt."""
        user_key = first_name.lower().strip()
        
        try:
            # Kijk of de leerling al bestaat
            response = self.client.table(self.table_name).select("*").eq("user_key", user_key).execute()
            if len(response.data) > 0:
                return False  # Naam is al in gebruik
            
            # Voeg nieuwe leerling toe
            new_student: Dict[str, Any] = {
                "user_key": user_key,
                "first_name": first_name,
                "class_name": student_class,
                "hashed_code": self._hash_password(reg_code)
            }
            self.client.table(self.table_name).insert(new_student).execute()
            return True
        except Exception as e:
            st.error(f"Er ging iets mis in de machinekamer: {e}")
            return False

    def login_student(self, first_name: str, reg_code: str) -> Optional[StudentProfile]:
        """Haalt data uit Supabase om inlog te verifiëren."""
        user_key = first_name.lower().strip()
        
        try:
            response = self.client.table(self.table_name).select("*").eq("user_key", user_key).execute()
            
            if len(response.data) == 0:
                return None  # Leerling niet gevonden
                
            student_data = response.data[0]
            
            # Wachtwoord controle
            if student_data["hashed_code"] == self._hash_password(reg_code):
                return StudentProfile(
                    first_name=student_data["first_name"],
                    student_class=student_data["class_name"],
                    is_authenticated=True
                )
            return None # Verkeerd wachtwoord
        except Exception as e:
            st.error(f"Systeem kon login niet verwerken: {e}")
            return None

# Activeer de butler zodra het script start
db_butler = SupabaseButler()

# ==========================================
# DEEL 3: SCHERMEN (User Interface & Etalage)
# ==========================================

def init_session() -> None:
    """Zorgt dat de rugzak (session_state) van de bezoeker klaar staat."""
    if 'current_user' not in st.session_state:
        st.session_state.current_user = StudentProfile(first_name="", student_class="")

def render_auth_screen() -> None:
    """Toont de inlog- en registratiedeuren."""
    st.title("⚡ Welcome to the vvXP Tracker")
    st.markdown("Track je progressie, verdien XP en verbeter je Engels.")
    
    tab_login, tab_register = st.tabs(["🔐 Login", "📝 Registreren"])
    
    with tab_register:
        st.subheader("Nieuw profiel aanmaken")
        with st.form("register_form"):
            new_name = st.text_input("Voornaam (Dit wordt je inlognaam)")
            new_class = st.selectbox("Klas", CLASSES)
            new_code = st.text_input("Bedenk een Registratiecode (Wachtwoord)", type="password")
            
            if st.form_submit_button("Maak profiel aan"):
                if new_name and new_code:
                    succes = db_butler.register_student(new_name, new_class, new_code)
                    if succes:
                        st.success("Profiel aangemaakt! Ga naar de Login tab om binnen te komen.")
                    else:
                        st.error("Deze voornaam is al in gebruik. Kies een andere of log in.")
                else:
                    st.warning("Vul alle velden in!")

    with tab_login:
        st.subheader("Ik heb al een profiel")
        with st.form("login_form"):
            login_name = st.text_input("Voornaam")
            login_code = st.text_input("Registratiecode", type="password")
            
            if st.form_submit_button("Enter vvXP Tracker"):
                user_profile = db_butler.login_student(login_name, login_code)
                if user_profile:
                    st.session_state.current_user = user_profile
                    st.rerun() # Herlaad de pagina om het dashboard te tonen
                else:
                    st.error("Oeps! Verkeerde naam of registratiecode.")

def render_radar_chart() -> None:
    """Tekent de radar grafiek."""
    st.subheader("Your Growth Radar")
    
    student_skills = [4, 5, 3, 4, 4] # Dummy data, dit automatiseren we later
    class_skills = list(CLASS_AVG_SKILLS.values())
    categories = list(CLASS_AVG_SKILLS.keys())
    
    fig_radar = go.Figure()
    
    fig_radar.add_trace(go.Scatterpolar(
        r=class_skills, theta=categories, fill='toself', 
        name=f'{st.session_state.current_user.student_class} Average',
        line_color='rgba(255, 255, 255, 0.4)', fillcolor='rgba(255, 255, 255, 0.1)'
    ))
    
    fig_radar.add_trace(go.Scatterpolar(
        r=student_skills, theta=categories, fill='toself', name='Your Score',
        line_color='#00f2fe', fillcolor='rgba(0, 242, 254, 0.4)'
    ))
    
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 5], gridcolor='rgba(255,255,255,0.2)')),
        showlegend=True,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=20, b=20)
    )
    st.plotly_chart(fig_radar, use_container_width=True)

def render_dashboard() -> None:
    """Het hoofdscherm (Werkplaats) als de student is ingelogd."""
    user = st.session_state.current_user
    
    col1, col2 = st.columns([8, 1])
    with col1:
        st.title(f"Sup {user.first_name}! 👋")
    with col2:
        if st.button("Logout"):
            st.session_state.current_user = StudentProfile(first_name="", student_class="")
            st.rerun()
            
    st.markdown(f"**Klas:** {user.student_class} | **Status:** vvXP Tracking Actief")
    st.markdown("---")
    
    tab_pulse, tab_reflection = st.tabs(["🔥 Pulse Check & Dashboard", "📝 Post-Evaluation Reflection"])
    
    with tab_pulse:
        col_form, col_charts = st.columns([1, 1.2]) 
        
        with col_form:
            st.subheader("Weekly Pulse Check")
            with st.form("pulse_form"):
                st.markdown("**1. Class Engagement**")
                st.select_slider(
                    "How active were you in class today?",
                    options=["Very passive", "Passive", "Neutral", "Active", "Very active"]
                )
                
                st.markdown("**2. Language Care**")
                st.radio("Did you try to answer in full sentences?", ["Yes", "Sometimes", "No", "N/A"], horizontal=True)
                st.radio("Did you search for the EXACT right words?", ["Yes", "Sometimes", "No", "N/A"], horizontal=True)
                
                st.markdown("**3. Out-of-class Engagement**")
                st.select_slider(
                    "Time ACTIVELY spent on English outside of class?",
                    options=["Not engaged", "15 mins", "15-30 mins", "30-60 mins", "+60 mins"]
                )
                
                if st.form_submit_button("🚀 Submit Pulse"):
                    st.success("Pulse logged! Keep up the good work. (Wordt nog niet opgeslagen)")
        
        with col_charts:
            render_radar_chart()

    with tab_reflection:
         st.info("The Post-Evaluation Reflection tab is under construction! 🚧")

# ==========================================
# DEEL 4: DE MOTOR (Het startpunt)
# ==========================================

def main() -> None:
    """De hoofdschakelaar van de applicatie."""
    init_session()
    
    # Structural Pattern Matching (Python 3.10+) of een simpele if/else voor navigatie
    if not st.session_state.current_user.is_authenticated:
        render_auth_screen()
    else:
        render_dashboard()

# Python conventie: Start het script alleen als het direct wordt uitgevoerd
if __name__ == "__main__":
    main()
