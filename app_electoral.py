import streamlit as st
import pandas as pd
import sqlite3
import google.generativeai as genai
import json
from PIL import Image
from datetime import datetime

# Configuración de la página
st.set_page_config(
    page_title="Sistema Electoral Regional y Municipal",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 1. BASE DE DATOS CENTRALIZADA (SQLite) ---
def init_db():
    conn = sqlite3.connect("votos_electorales_multiples.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS actas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave_unica TEXT UNIQUE,
            mesa TEXT,
            tipo_eleccion TEXT,
            departamento TEXT,
            provincia TEXT,
            distrito TEXT,
            emitidos INTEGER,
            personero TEXT,
            fecha_hora TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS votos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acta_id INTEGER,
            partido TEXT,
            votos INTEGER,
            FOREIGN KEY(acta_id) REFERENCES actas(id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- 2. CONFIGURACIÓN DE IA (Google Gemini Gratis) ---
gemini_key = st.secrets.get("GEMINI_API_KEY", "")

# Menu lateral
st.sidebar.title("Navegación")
opcion_menu = st.sidebar.radio("Ir a:", ["📋 Enviar Foto (Personero)", "📊 Tablero Central de Cómputo"])

# --- VISTA PERSONERO ---
if opcion_menu == "📋 Enviar Foto (Personero)":
    st.header("📸 Registro de Cartel de Resultados")
    
    personero = st.text_input("Código / Nombre del Personero:", value="Personero1")
    
    tipo_eleccion = st.selectbox(
        "Seleccione Tipo de Elección:",
        ["Automatico (Detectar por IA)", "PRESIDENTE / GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]
    )
    
    foto = st.file_uploader("Capturar / Subir Foto del Cartel", type=["jpg", "jpeg", "png"])
    
    if foto is not None:
        image = Image.open(foto)
        st.image(image, caption="Foto cargada", use_column_width=True)
        
        if st.button("🚀 Procesar e Ingresar a Base de Datos Central", type="primary"):
            if not gemini_key:
                st.error("Falta configurar la clave GEMINI_API_KEY en los Secrets de Streamlit.")
            else:
                with st.spinner("La IA de Google está analizando la imagen..."):
                    try:
                        genai.configure(api_key=gemini_key)
                        model = genai.GenerativeModel('gemini-3.8-flash')
                        
                        prompt = """
                        Analiza este cartel de resultados electorales.
                        Extrae la siguiente información en formato JSON estricto:
                        {
                            "mesa": "numero de mesa o Desconocido",
                            "departamento": "nombre o Desconocido",
                            "provincia": "nombre o Desconocido",
                            "distrito": "nombre o Desconocido",
                            "tipo_eleccion": "PRESIDENTE / GOBERNADOR REGIONAL, CONSEJERO REGIONAL, ALCALDE PROVINCIAL, o ALCALDE DISTRITAL",
                            "emitidos": numero_total_votos_emitidos_o_0,
                            "votos": [
                                {"partido": "Nombre Partido 1", "votos": numero},
                                {"partido": "Nombre Partido 2", "votos": numero}
                            ]
                        }
                        Responde UNICAMENTE con el JSON, sin marcas de markdown.
                        """
                        
                        response = model.generate_content([prompt, image])
                        text_response = response.text.strip().replace("```json", "").replace("```", "")
                        data = json.loads(text_response)
                        
                        eleccion_final = data.get("tipo_eleccion", "GENERAL") if tipo_eleccion.startswith("Automatico") else tipo_eleccion
                        mesa_num = str(data.get("mesa", "000000"))
                        clave = f"{mesa_num}_{eleccion_final}"
                        
                        conn = sqlite3.connect("votos_electorales_multiples.db")
                        c = conn.cursor()
                        
                        c.execute('''
                            INSERT INTO actas (clave_unica, mesa, tipo_eleccion, departamento, provincia, distrito, emitidos, personero, fecha_hora)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (clave, mesa_num, eleccion_final, data.get("departamento", ""), data.get("provincia", ""), data.get("distrito", ""), data.get("emitidos", 0), personero, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                        
                        acta_id = c.lastrowid
                        
                        for item in data.get("votos", []):
                            c.execute('INSERT INTO votos (acta_id, partido, votos) VALUES (?, ?, ?)', (acta_id, item.get("partido", "OTRO"), item.get("votos", 0)))
                            
                        conn.commit()
                        conn.close()
                        
                        st.success("¡Acta procesada y guardada exitosamente en la base de datos central!")
                        st.json(data)
                        
                    except sqlite3.IntegrityError:
                        st.warning("⚠️ Esta mesa y tipo de elección ya fue registrada anteriormente.")
                    except Exception as e:
                        st.error(f"Error procesando la imagen: {e}")

# --- VISTA TABLERO CENTRAL ---
else:
    st.title("🏛️ Centro Electoral Regional")
    st.subheader("Tablero Central de Cómputo")
    
    conn = sqlite3.connect("votos_electorales_multiples.db")
    df_actas = pd.read_sql_query("SELECT * FROM actas", conn)
    df_votos = pd.read_sql_query("SELECT v.*, a.tipo_eleccion FROM votos v JOIN actas a ON v.acta_id = a.id", conn)
    conn.close()
    
    elecciones = ["GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]
    tabs = st.tabs([f"🏛️ {e}" for e in elecciones])
    
    for idx, e in enumerate(elecciones):
        with tabs[idx]:
            st.header(f"Resultados Consolidados: {e}")
            df_sub = df_votos[df_votos["tipo_eleccion"].str.contains(e, case=False, na=False)]
            if not df_sub.empty:
                res = df_sub.groupby("partido")["votos"].sum().reset_index().sort_values(by="votos", ascending=False)
                st.dataframe(res, use_container_width=True)
                st.bar_chart(res.set_index("partido"))
            else:
                st.info(f"Aún no hay votos registrados para {e}.")

    st.subheader("📋 Lista General de Mesas y Elecciones Registradas")
    st.dataframe(df_actas, use_container_width=True)
