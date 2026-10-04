import streamlit as st
import google.generativeai as genai
import sqlite3
import pandas as pd
from PIL import Image
import io
import json

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Conteo Electoral Regional y Municipal", layout="wide")
st.title("🗳️ Sistema de Conteo Electoral Completo")

# --- 2. BASE DE DATOS LIGERA (SOLO NÚMEROS Y TEXTO) ---
conn = sqlite3.connect('votos_electorales_v5.db', check_same_thread=False)
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS actas (
        numero_mesa TEXT PRIMARY KEY,
        pres_reg_p1 INTEGER DEFAULT 0,
        pres_reg_p2 INTEGER DEFAULT 0,
        cons_reg_p1 INTEGER DEFAULT 0,
        cons_reg_p2 INTEGER DEFAULT 0,
        alc_prov_p1 INTEGER DEFAULT 0,
        alc_prov_p2 INTEGER DEFAULT 0,
        alc_dist_p1 INTEGER DEFAULT 0,
        alc_dist_p2 INTEGER DEFAULT 0,
        votos_blancos INTEGER DEFAULT 0,
        votos_nulos INTEGER DEFAULT 0,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# --- 3. OPTIMIZACIÓN DE IMAGEN EN MEMORIA RAM (CERO GUARDADO EN DISCO) ---
def optimizar_imagen(image_pil, max_size=(1280, 1280), quality=75):
    img = image_pil.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    buffer.seek(0)
    return Image.open(buffer)

# --- 4. FUNCIÓN PARA OBTENER UN MODELO VIGENTE AUTOMÁTICAMENTE ---
def obtener_modelo_activo():
    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # Buscar el mejor modelo flash disponible en tu cuenta
        for m in modelos:
            if 'flash' in m.lower():
                return genai.GenerativeModel(m)
        return genai.GenerativeModel(modelos[0])
    except Exception:
        # Respaldo en caso de error en listado
        return genai.GenerativeModel('gemini-2.5-flash')

# --- 5. SECCIÓN DEL PERSONERO (SIN PREVISUALIZACIÓN NI GUARDADO DE IMAGEN) ---
st.subheader("📷 Registro de Acta Electoral")

foto = st.file_uploader("Selecciona o toma la foto del acta electoral", type=["jpg", "jpeg", "png"])

if foto is not None:
    imagen_pil = Image.open(foto)
    st.info("📷 Foto cargada en memoria RAM. Cero imágenes guardadas.")
    
    if st.button("🚀 Procesar Foto y Extraer Todos los Cargos", type="primary"):
        with st.spinner("Leyendo resultados de los 4 cargos electorales..."):
            try:
                api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
                if not api_key:
                    st.error("Error: No se encontró la GEMINI_API_KEY en los Secrets.")
                    st.stop()
                
                genai.configure(api_key=api_key)
                img_opt = optimizar_imagen(imagen_pil)
                
                prompt = """
                Analiza esta foto de acta electoral y extrae los votos para los cargos solicitados.
                Devuelve ÚNICAMENTE un objeto JSON válido con este formato exacto:
                {
                    "numero_mesa": "cadena con el numero de mesa",
                    "pres_reg_p1": entero_numero,
                    "pres_reg_p2": entero_numero,
                    "cons_reg_p1": entero_numero,
                    "cons_reg_p2": entero_numero,
                    "alc_prov_p1": entero_numero,
                    "alc_prov_p2": entero_numero,
                    "alc_dist_p1": entero_numero,
                    "alc_dist_p2": entero_numero,
                    "votos_blancos": entero_numero,
                    "votos_nulos": entero_numero
                }
                Si un cargo o valor no es legible o no está presente, asigna 0.
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
                
                datos = json.loads(res_text.strip())
                
                c.execute('''
                    INSERT OR REPLACE INTO actas (
                        numero_mesa, pres_reg_p1, pres_reg_p2, cons_reg_p1, cons_reg_p2,
                        alc_prov_p1, alc_prov_p2, alc_dist_p1, alc_dist_p2,
                        votos_blancos, votos_nulos
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(datos.get("numero_mesa", "Desconocida")),
                    int(datos.get("pres_reg_p1", 0)),
                    int(datos.get("pres_reg_p2", 0)),
                    int(datos.get("cons_reg_p1", 0)),
                    int(datos.get("cons_reg_p2", 0)),
                    int(datos.get("alc_prov_p1", 0)),
                    int(datos.get("alc_prov_p2", 0)),
                    int(datos.get("alc_dist_p1", 0)),
                    int(datos.get("alc_dist_p2", 0)),
                    int(datos.get("votos_blancos", 0)),
                    int(datos.get("votos_nulos", 0))
                ))
                conn.commit()
                
                st.success(f"✅ ¡Votos de la Mesa N° {datos.get('numero_mesa')} registrados!")
                st.rerun()
                
            except Exception as e:
                st.error(f"Error al procesar: {str(e)}")

st.markdown("---")

# --- 6. RESULTADOS CONSOLIDADOS Y CONSULTA INTERACTIVA POR MESA ---
st.header("📊 Resumen General de Candidaturas")

df = pd.read_sql_query("SELECT * FROM actas", conn)

if not df.empty:
    st.subheader("🏛️ Totales Acumulados")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Pres. Regional (P1 / P2)", f"{df['pres_reg_p1'].sum()} | {df['pres_reg_p2'].sum()}")
    t2.metric("Cons. Regional (P1 / P2)", f"{df['cons_reg_p1'].sum()} | {df['cons_reg_p2'].sum()}")
    t3.metric("Alc. Provincial (P1 / P2)", f"{df['alc_prov_p1'].sum()} | {df['alc_prov_p2'].sum()}")
    t4.metric("Alc. Distrital (P1 / P2)", f"{df['alc_dist_p1'].sum()} | {df['alc_dist_p2'].sum()}")
    
    st.markdown("---")
    st.subheader("📋 Mesas Registradas (Haz clic en una mesa para ver todos los cargos)")

    for index, row in df.iterrows():
        col_btn, col_res, col_f = st.columns([3, 6, 3])
        
        if col_btn.button(f"🔍 Mesa N° {row['numero_mesa']}", key=f"btn_{row['numero_mesa']}"):
            
            @st.dialog(f"🔎 Desglose Completo: Mesa N° {row['numero_mesa']}")
            def mostrar_detalle_mesa(mesa_id):
                c.execute("SELECT * FROM actas WHERE numero_mesa = ?", (mesa_id,))
                res = c.fetchone()
                if res:
                    st.write(f"### Mesa N° {mesa_id}")
                    
                    st.subheader("👤 Presidente Regional")
                    r1, r2 = st.columns(2)
                    r1.metric("Partido 1", res[1])
                    r2.metric("Partido 2", res[2])
                    
                    st.subheader("🏛️ Consejero Regional")
                    c1, c2 = st.columns(2)
                    c1.metric("Partido 1", res[3])
                    c2.metric("Partido 2", res[4])
                    
                    st.subheader("🏢 Alcalde Provincial")
                    p1, p2 = st.columns(2)
                    p1.metric("Partido 1", res[5])
                    p2.metric("Partido 2", res[6])
                    
                    st.subheader("🏘️ Alcalde Distrital")
                    d1, d2 = st.columns(2)
                    d1.metric("Partido 1", res[7])
                    d2.metric("Partido 2", res[8])
                    
                    st.divider()
                    b1, b2 = st.columns(2)
                    b1.metric("Votos Blancos", res[9])
                    b2.metric("Votos Nulos", res[10])
                    st.caption(f"Registrado el: {res[11]}")
            
            mostrar_detalle_mesa(str(row['numero_mesa']))
            
        col_res.write(f"P.Reg: {row['pres_reg_p1']}/{row['pres_reg_p2']} | C.Reg: {row['cons_reg_p1']}/{row['cons_reg_p2']} | A.Prov: {row['alc_prov_p1']}/{row['alc_prov_p2']} | A.Dist: {row['alc_dist_p1']}/{row['alc_dist_p2']}")
        col_f.caption(f"{row['fecha_registro']}")

else:
    st.info("Aún no se han ingresado actas electorales.")
