import streamlit as st
import pandas as pd
import sqlite3
import google.generativeai as genai
import json
from PIL import Image
import io
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Sistema Electoral Regional y Municipal",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 1. BASE DE DATOS CENTRALIZADA (SQLite) ---
def init_db():
    conn = sqlite3.connect("votos_electorales_multiples.db", check_same_thread=False)
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

# --- 2. OPTIMIZACIÓN DE IMAGEN (SOLO EN RAM) ---
def optimizar_imagen(image_pil, max_size=(1280, 1280), quality=75):
    img = image_pil.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    buffer.seek(0)
    return Image.open(buffer)

# --- 3. NAVEGACIÓN ---
st.sidebar.title("Navegación")
opcion_menu = st.sidebar.radio("Ir a:", ["📋 Enviar Foto (Personero)", "📊 Tablero Central de Cómputo"])

# --- VISTA PERSONERO (SIN MOSTRAR NI GUARDAR IMÁGENES) ---
if opcion_menu == "📋 Enviar Foto (Personero)":
    st.header("📸 Registro de Cartel de Resultados")
    
    personero = st.text_input("Código / Nombre del Personero:", value="Personero1")
    
    tipo_eleccion = st.selectbox(
        "Seleccione Tipo de Elección:",
        ["Automatico (Detectar por IA)", "PRESIDENTE / GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]
    )
    
    foto = st.file_uploader("Capturar / Seleccionar Foto del Cartel", type=["jpg", "jpeg", "png"])
    
    if foto is not None:
        imagen_pil = Image.open(foto)
        st.info("📷 Foto cargada en memoria RAM (no se mostrará ni almacenará en el servidor).")
        
        if st.button("🚀 Procesar e Ingresar a Base de Datos Central", type="primary"):
            gemini_key = st.secrets.get("GEMINI_API_KEY", "").strip()
            if not gemini_key:
                st.error("Falta configurar la clave GEMINI_API_KEY en los Secrets de Streamlit.")
            else:
                with st.spinner("La IA de Google está analizando la imagen..."):
                    try:
                        genai.configure(api_key=gemini_key)
                        img_opt = optimizar_imagen(imagen_pil)
                        
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
                        
                        # Modelo oficial actualizado
                        try:
                            model = genai.GenerativeModel('gemini-2.5-flash')
                        except Exception:
                            model = genai.GenerativeModel('gemini-1.5-flash')
                        
                        generation_config = genai.GenerationConfig(
                            temperature=0.1,
                            response_mime_type="application/json"
                        )
                        
                        response = model.generate_content([prompt, img_opt], generation_config=generation_config)
                        
                        res_text = response.text.strip()
                        if res_text.startswith("```json"):
                            res_text = res_text[7:]
                        if res_text.startswith("```"):
                            res_text = res_text[3:]
                        if res_text.endswith("```"):
                            res_text = res_text[:-3]
                        
                        data = json.loads(res_text.strip())
                        
                        eleccion_final = data.get("tipo_eleccion", "GENERAL") if tipo_eleccion.startswith("Automatico") else tipo_eleccion
                        mesa_num = str(data.get("mesa", "000000"))
                        clave = f"{mesa_num}_{eleccion_final}"
                        
                        conn = sqlite3.connect("votos_electorales_multiples.db", check_same_thread=False)
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
                        
                        st.success(f"✅ ¡Mesa N° {mesa_num} ({eleccion_final}) procesada y guardada exitosamente!")
                        st.json(data)
                        
                    except sqlite3.IntegrityError:
                        st.warning("⚠️ Esta mesa y tipo de elección ya fueron registradas anteriormente.")
                    except Exception as e:
                        st.error(f"Error procesando la imagen: {e}")

# --- VISTA TABLERO CENTRAL DE CÓMPUTO ---
else:
    st.title("🏛️ Centro Electoral Regional y Municipal")
    
    conn = sqlite3.connect("votos_electorales_multiples.db", check_same_thread=False)
    df_actas = pd.read_sql_query("SELECT * FROM actas", conn)
    df_votos = pd.read_sql_query("SELECT v.*, a.tipo_eleccion, a.mesa, a.departamento, a.provincia, a.distrito FROM votos v JOIN actas a ON v.acta_id = a.id", conn)
    conn.close()

    # --- BOTÓN DE CONTEO TOTAL GENERAL ---
    st.subheader("📊 Cómputo General")
    col_btn, col_blank = st.columns([1, 3])
    
    with col_btn:
        if st.button("🧮 Ver Conteo Total de Votos Emitidos", type="primary", use_container_width=True):
            @st.dialog("📊 Conteo Total Nacional / Regional")
            def mostrar_totales_globales():
                if not df_votos.empty:
                    st.write("### 🗳
