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

# --- 2. BASE DE DATOS LIGERA (SOLO TEXTO Y NÚMEROS) ---
conn = sqlite3.connect('votos_electorales_v4.db', check_same_thread=False)
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS actas (
        numero_mesa TEXT PRIMARY KEY,
        votos_partido_1 INTEGER,
        votos_partido_2 INTEGER,
        votos_blancos INTEGER,
        votos_nulos INTEGER,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# --- 3. OPTIMIZACIÓN DE IMAGEN PARA MINIMIZAR USO DE API ---
def optimizar_imagen(image_pil, max_size=(1280, 1280), quality=75):
    img = image_pil.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    buffer.seek(0)
    return Image.open(buffer)

# --- 4. SECCIÓN DEL PERSONERO (SUBIR FOTO Y PROCESAR) ---
st.subheader("📷 Registro de Acta (Personeros)")

foto = st.file_uploader("Toma o sube la foto del acta electoral", type=["jpg", "jpeg", "png"])

if foto is not None:
    imagen_pil = Image.open(foto)
    st.image(imagen_pil, caption="Vista previa de foto", width=200)
    
    if st.button("🚀 Procesar Foto y Guardar Votos", type="primary"):
        with st.spinner("Procesando datos en 2 segundos..."):
            try:
                api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
                if not api_key:
                    st.error("Error: No se encontró la GEMINI_API_KEY en los Secrets.")
                    st.stop()
                
                genai.configure(api_key=api_key)
                img_opt = optimizar_imagen(imagen_pil)
                
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
                
                # Probar modelos 2.0 / 2.5 / 1.5 según disponibilidad
                try:
                    model = genai.GenerativeModel('gemini-2.0-flash')
                except Exception:
                    try:
                        model = genai.GenerativeModel('gemini-2.5-flash')
                    except Exception:
                        model = genai.GenerativeModel('gemini-1.5-flash-8b')
                
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
                
                # Solo guardamos los números y el ID de mesa en la base de datos
                c.execute('''
                    INSERT OR REPLACE INTO actas (numero_mesa, votos_partido_1, votos_partido_2, votos_blancos, votos_nulos)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    str(datos.get("numero_mesa", "Desconocida")),
                    int(datos.get("votos_partido_1", 0)),
                    int(datos.get("votos_partido_2", 0)),
                    int(datos.get("votos_blancos", 0)),
                    int(datos.get("votos_nulos", 0))
                ))
                conn.commit()
                
                st.success(f"✅ ¡Votos de la Mesa N° {datos.get('numero_mesa')} guardados!")
                st.rerun()
                
            except Exception as e:
                st.error(f"Error al procesar: {str(e)}")

st.markdown("---")

# --- 5. RESULTADOS CONSOLIDADOS Y CONSULTA INTERACTIVA POR MESA ---
st.header("📊 Resultados Consolidados")

df = pd.read_sql_query("SELECT numero_mesa, votos_partido_1, votos_partido_2, votos_blancos, votos_nulos, fecha_registro FROM actas", conn)

if not df.empty:
    # Totales Globales
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Partido 1", f"{df['votos_partido_1'].sum():,}")
    col2.metric("Partido 2", f"{df['votos_partido_2'].sum():,}")
    col3.metric("Blancos / Nulos", f"{(df['votos_blancos'].sum() + df['votos_nulos'].sum()):,}")
    col4.metric("Mesas Procesadas", len(df))
    
    st.markdown("---")
    st.subheader("📋 Mesas Registradas (Haz clic para ver el detalle)")

    # Botones por mesa que abren ventana emergente
    for index, row in df.iterrows():
        col_btn, col_p1, col_p2, col_bn, col_f = st.columns([3, 2, 2, 2, 3])
        
        if col_btn.button(f"🔍 Mesa N° {row['numero_mesa']}", key=f"btn_{row['numero_mesa']}"):
            
            # Modal emergente con los resultados numéricos de esa mesa
            @st.dialog(f"🔎 Conteo Exclusivo: Mesa N° {row['numero_mesa']}")
            def mostrar_detalle_mesa(mesa_id):
                c.execute("SELECT votos_partido_1, votos_partido_2, votos_blancos, votos_nulos, fecha_registro FROM actas WHERE numero_mesa = ?", (mesa_id,))
                res = c.fetchone()
                if res:
                    p1, p2, pb, pn, fecha = res
                    
                    st.write(f"### Mesa N° {mesa_id}")
                    m1, m2 = st.columns(2)
                    m1.metric("Votos Partido 1", p1)
                    m2.metric("Votos Partido 2", p2)
                    
                    m3, m4 = st.columns(2)
                    m3.metric("Votos Blancos", pb)
                    m4.metric("Votos Nulos", pn)
                    
                    st.divider()
                    st.caption(f"Fecha/Hora de Registro: {fecha}")
            
            mostrar_detalle_mesa(str(row['numero_mesa']))
            
        col_p1.write(f"**P1:** {row['votos_partido_1']}")
        col_p2.write(f"**P2:** {row['votos_partido_2']}")
        col_bn.write(f"**B/N:** {row['votos_blancos'] + row['votos_nulos']}")
        col_f.caption(f"{row['fecha_registro']}")

else:
    st.info("Aún no se han registrado actas. Sube una foto arriba para comenzar.")
