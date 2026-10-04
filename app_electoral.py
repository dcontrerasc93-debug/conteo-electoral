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

# --- 1. BASE DE DATOS CENTRALIZADA Y MIGRACIÓN AUTOMÁTICA (SQLite) ---
def init_db():
    conn = sqlite3.connect("votos_electorales_multiples.db", check_same_thread=False)
    c = conn.cursor()
    
    # Crear tablas principales
    c.execute('''
        CREATE TABLE IF NOT EXISTS actas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave_unica TEXT UNIQUE,
            mesa TEXT,
            tipo_eleccion TEXT,
            departamento TEXT,
            provincia TEXT,
            distrito TEXT,
            emitidos INTEGER DEFAULT 0,
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

    # Migración automática para asegurar que la columna 'emitidos' y otras existan
    c.execute("PRAGMA table_info(actas)")
    columnas_existentes = [col[1] for col in c.fetchall()]
    
    columnas_requeridas = {
        "departamento": "TEXT",
        "provincia": "TEXT",
        "distrito": "TEXT",
        "emitidos": "INTEGER DEFAULT 0",
        "personero": "TEXT",
        "fecha_hora": "TEXT"
    }

    for col, tipo in columnas_requeridas.items():
        if col not in columnas_existentes:
            try:
                c.execute(f"ALTER TABLE actas ADD COLUMN {col} {tipo}")
            except Exception:
                pass

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

# --- 3. SELECCIÓN DE MODELO ACTIVO EN TIEMPO REAL ---
def obtener_modelo_activo():
    try:
        return genai.GenerativeModel('gemini-3.8-flash')
    except Exception:
        pass

    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m in modelos:
            if 'flash' in m.lower():
                return genai.GenerativeModel(m)
        if modelos:
            return genai.GenerativeModel(modelos[0])
    except Exception:
        pass

    return genai.GenerativeModel('gemini-3.8-flash')

# --- 4. NAVEGACIÓN ---
st.sidebar.title("Navegacion")
opcion_menu = st.sidebar.radio("Ir a:", ["Enviar Foto (Personero)", "Tablero Central de Computo"])

# --- VISTA PERSONERO (SIN MOSTRAR NI GUARDAR IMÁGENES) ---
if opcion_menu == "Enviar Foto (Personero)":
    st.header("Registro de Cartel de Resultados")
    
    personero = st.text_input("Codigo / Nombre del Personero:", value="Personero1")
    
    tipo_eleccion = st.selectbox(
        "Seleccione Tipo de Eleccion:",
        ["Automatico (Detectar por IA)", "PRESIDENTE / GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]
    )
    
    foto = st.file_uploader("Capturar / Seleccionar Foto del Cartel", type=["jpg", "jpeg", "png"])
    
    if foto is not None:
        imagen_pil = Image.open(foto)
        st.info("Foto cargada en memoria RAM (no se mostrara ni almacenara en el servidor).")
        
        if st.button("Procesar e Ingresar a Base de Datos Central", type="primary"):
            gemini_key = st.secrets.get("GEMINI_API_KEY", "").strip()
            if not gemini_key:
                st.error("Falta configurar la clave GEMINI_API_KEY en los Secrets de Streamlit.")
            else:
                with st.spinner("La IA de Google esta analizando la imagen..."):
                    try:
                        genai.configure(api_key=gemini_key)
                        img_opt = optimizar_imagen(imagen_pil)
                        
                        prompt = """
                        Analiza este cartel de resultados electorales.
                        Extrae la siguiente informacion en formato JSON estricto:
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
                        
                        model = obtener_modelo_activo()
                        
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
                        
                        st.success(f"Mesa N {mesa_num} ({eleccion_final}) procesada y guardada exitosamente!")
                        st.json(data)
                        
                    except sqlite3.IntegrityError:
                        st.warning("Esta mesa y tipo de eleccion ya fueron registradas anteriormente.")
                    except Exception as e:
                        st.error(f"Error procesando la imagen: {e}")

# --- VISTA TABLERO CENTRAL DE CÓMPUTO ---
else:
    st.title("Centro Electoral Regional y Municipal")
    
    conn = sqlite3.connect("votos_electorales_multiples.db", check_same_thread=False)
    df_actas = pd.read_sql_query("SELECT * FROM actas", conn)
    df_votos = pd.read_sql_query("SELECT v.*, a.tipo_eleccion, a.mesa, a.departamento, a.provincia, a.distrito FROM votos v JOIN actas a ON v.acta_id = a.id", conn)
    conn.close()

    # --- BOTÓN DE CONTEO TOTAL GENERAL ---
    st.subheader("Computo General")
    col_btn, col_blank = st.columns([1, 3])
    
    with col_btn:
        if st.button("Ver Conteo Total de Votos Emitidos", type="primary", use_container_width=True):
            @st.dialog("Conteo Total Nacional / Regional")
            def mostrar_totales_globales():
                if not df_votos.empty:
                    st.write("### Total de Votos por Eleccion y Partido")
                    for e in ["GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]:
                        st.markdown(f"#### {e}")
                        df_sub = df_votos[df_votos["tipo_eleccion"].str.contains(e, case=False, na=False)]
                        if not df_sub.empty:
                            totales = df_sub.groupby("partido")["votos"].sum().reset_index().sort_values(by="votos", ascending=False)
                            st.dataframe(totales, use_container_width=True)
                            st.caption(f"Total Votos Emitidos en este cargo: {totales['votos'].sum():,}")
                        else:
                            st.info(f"Sin registros para {e}.")
                        st.divider()
                else:
                    st.info("No hay datos cargados todavia.")
            
            mostrar_totales_globales()

    st.markdown("---")

    # --- PESTAÑAS POR TIPO DE ELECCIÓN ---
    elecciones = ["GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL"]
    tabs = st.tabs([f"{e}" for e in elecciones])
    
    for idx, e in enumerate(elecciones):
        with tabs[idx]:
            st.header(f"Resultados Consolidados: {e}")
            df_sub = df_votos[df_votos["tipo_eleccion"].str.contains(e, case=False, na=False)]
            if not df_sub.empty:
                res = df_sub.groupby("partido")["votos"].sum().reset_index().sort_values(by="votos", ascending=False)
                st.dataframe(res, use_container_width=True)
                st.bar_chart(res.set_index("partido"))
            else:
                st.info(f"Aun no hay votos registrados para {e}.")

    st.markdown("---")

    # --- LISTA GENERAL DE MESAS CON VISTA DETALLADA AL HACER CLIC ---
    st.subheader("Mesas Registradas (Haz clic en una mesa para ver su desglose)")
    
    if not df_actas.empty:
        for idx, row in df_actas.iterrows():
            c1, c2, c3, c4 = st.columns([2, 3, 3, 2])
            
            if c1.button(f"Mesa N {row['mesa']}", key=f"mesa_btn_{row['id']}"):
                
                @st.dialog(f"Detalle de Acta: Mesa N {row['mesa']}")
                def mostrar_detalle_acta(acta_id, mesa_num, tipo_e):
                    st.write(f"### Mesa N {mesa_num}")
                    st.write(f"**Tipo de Eleccion:** {tipo_e}")
                    st.write(f"**Ubicacion:** {row.get('departamento', '')} - {row.get('provincia', '')} - {row.get('distrito', '')}")
                    st.write(f"**Personero:** {row.get('personero', '')} | **Fecha:** {row.get('fecha_hora', '')}")
                    st.divider()
                    
                    conn_dialog = sqlite3.connect("votos_electorales_multiples.db", check_same_thread=False)
                    df_votos_acta = pd.read_sql_query("SELECT partido, votos FROM votos WHERE acta_id = ?", conn_dialog, params=(acta_id,))
                    conn_dialog.close()
                    
                    if not df_votos_acta.empty:
                        st.dataframe(df_votos_acta.sort_values(by="votos", ascending=False), use_container_width=True)
                    else:
                        st.info("Sin detalle de votos grabado para esta mesa.")
                
                mostrar_detalle_acta(row['id'], row['mesa'], row['tipo_eleccion'])
                
            c2.write(f"**Eleccion:** {row['tipo_eleccion']}")
            c3.write(f"**Lugar:** {row.get('departamento', '')} / {row.get('provincia', '')} / {row.get('distrito', '')}")
            c4.caption(f"{row.get('fecha_hora', '')}")
    else:
        st.info("Aun no se han ingresado actas electorales.")
