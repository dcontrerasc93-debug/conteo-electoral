import streamlit as st
import google.generativeai as genai
import sqlite3
import pandas as pd
from PIL import Image
import io
import json

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Conteo Electoral", layout="wide")
st.title("🗳️ Sistema de Conteo Electoral en Vivo")

# --- 2. CONEXIÓN A BASE DE DATOS SQLITE CON ALMACENAMIENTO DE IMAGEN ---
conn = sqlite3.connect('votos_electorales_v3.db', check_same_thread=False)
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS actas (
        numero_mesa TEXT PRIMARY KEY,
        votos_partido_1 INTEGER,
        votos_partido_2 INTEGER,
        votos_blancos INTEGER,
        votos_nulos INTEGER,
        imagen_blob BLOB,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# --- 3. OPTIMIZACIÓN DE IMAGEN ---
def optimizar_imagen(image_pil, max_size=(1280, 1280), quality=75):
    img = image_pil.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    buffer.seek(0)
    return Image.open(buffer), buffer.getvalue()

# --- 4. SECCIÓN DEL PERSONERO (SUBIR FOTO Y PROCESAR) ---
st.subheader("📷 Registro de Acta (Personeros)")

foto = st.file_uploader("Toma o sube la foto del acta electoral", type=["jpg", "jpeg", "png"])

if foto is not None:
    imagen_pil = Image.open(foto)
    st.image(imagen_pil, caption="Foto del Acta Cargada", width=250)
    
    if st.button("🚀 Procesar Foto y Guardar Acta", type="primary"):
        with st.spinner("Leyendo datos del acta con Gemini en 2-3 segundos..."):
            try:
                api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
                if not api_key:
                    st.error("Error: No se encontró la GEMINI_API_KEY en los Secrets de Streamlit.")
                    st.stop()
                
                genai.configure(api_key=api_key)
                img_opt, img_bytes = optimizar_imagen(imagen_pil)
                
                prompt = """
                Analiza esta foto de acta electoral y devuelve ÚNICAMENTE un objeto JSON válido con este formato exacto:
                {
                    "numero_mesa": "cadena con el numero de mesa",
                    "votos_partido_1": entero_numero,
                    "votos_partido_2": entero_numero,
                    "votos_blancos": entero_numero,
                    "votos_nulos": entero_numero
                }
                Si no estás seguro de algún valor pon 0.
                """
                
                model = genai.GenerativeModel('gemini-1.5-flash')
                generation_config = genai.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json"
                )
                
                response = model.generate_content([prompt, img_opt], generation_config=generation_config)
                datos = json.loads(response.text)
                
                c.execute('''
                    INSERT OR REPLACE INTO actas (numero_mesa, votos_partido_1, votos_partido_2, votos_blancos, votos_nulos, imagen_blob)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    str(datos.get("numero_mesa", "Desconocida")),
                    int(datos.get("votos_partido_1", 0)),
                    int(datos.get("votos_partido_2", 0)),
                    int(datos.get("votos_partido_1", 0)),
                    int(datos.get("votos_nulos", 0)),
                    sqlite3.Binary(img_bytes)
                ))
                conn.commit()
                
                st.success(f"✅ ¡Acta de la Mesa N° {datos.get('numero_mesa')} guardada correctamente!")
                st.rerun()
                
            except Exception as e:
                st.error(f"Error al procesar la imagen: {str(e)}")

st.markdown("---")

# --- 5. RESULTADOS CONSOLIDADOS Y SELECCIÓN INTERACTIVA POR BOTÓN ---
st.header("📊 Resultados Consolidados")

df = pd.read_sql_query("SELECT numero_mesa, votos_partido_1, votos_partido_2, votos_blancos, votos_nulos, fecha_registro FROM actas", conn)

if not df.empty:
    # Métricas Globales
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Partido 1", f"{df['votos_partido_1'].sum():,}")
    col2.metric("Partido 2", f"{df['votos_partido_2'].sum():,}")
    col3.metric("Blancos / Nulos", f"{(df['votos_blancos'].sum() + df['votos_nulos'].sum()):,}")
    col4.metric("Mesas Procesadas", len(df))
    
    st.markdown("---")
    st.subheader("📋 Lista de Mesas Procesadas (Haz clic en una para ver su ventana de detalle)")

    # Presentación interactiva donde cada número de mesa es un BOTÓN clicable
    for index, row in df.iterrows():
        col_btn, col_p1, col_p2, col_bn, col_f = st.columns([2, 2, 2, 2, 3])
        
        # Al hacer clic en el número de mesa, abre la ventana modal (dialog)
        if col_btn.button(f"🔍 Mesa N° {row['numero_mesa']}", key=f"btn_{row['numero_mesa']}"):
            
            # Modal emergente con el detalle de la mesa elegida
            @st.dialog(f"🔎 Detalle de la Mesa N° {row['numero_mesa']}")
            def mostrar_detalle_mesa(mesa_id):
                c.execute("SELECT votos_partido_1, votos_partido_2, votos_blancos, votos_nulos, imagen_blob, fecha_registro FROM actas WHERE numero_mesa = ?", (mesa_id,))
                res = c.fetchone()
                if res:
                    p1, p2, pb, pn, img_blob, fecha = res
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Partido 1", p1)
                    m2.metric("Partido 2", p2)
                    m3.metric("Blancos/Nulos", pb + pn)
                    
                    st.caption(f"Fecha de registro: {fecha}")
                    
                    if img_blob:
                        st.markdown("**Foto del Acta Original:**")
                        imagen_mesa = Image.open(io.BytesIO(img_blob))
                        st.image(imagen_mesa, use_column_width=True)
            
            mostrar_detalle_mesa(str(row['numero_mesa']))
            
        col_p1.write(f"**P1:** {row['votos_partido_1']}")
        col_p2.write(f"**P2:** {row['votos_partido_2']}")
        col_bn.write(f"**B/N:** {row['votos_blancos'] + row['votos_nulos']}")
        col_f.caption(f"{row['fecha_registro']}")

else:
    st.info("Aún no se han registrado actas. Sube una foto arriba para comenzar el conteo.")
