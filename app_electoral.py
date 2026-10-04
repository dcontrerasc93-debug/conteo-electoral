import streamlit as st
import sqlite3
import pandas as pd

# --- CONEXIÓN A LA BASE DE DATOS ---
conn = sqlite3.connect('votos_electorales_v2.db', check_same_thread=False)
c = conn.cursor()

# Crear tabla si no existe
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

# --- NAVEGACIÓN Y PESTAÑAS ---
st.title("🗳️ Sistema de Conteo Electoral en Vivo")

tab1, tab2 = st.tabs(["📊 Suma Total General", "🔍 Consulta por Número de Mesa"])

# ---------------------------------------------------------
# PESTAÑA 1: SUMA AUTOMÁTICA DE TODAS LAS MESAS
# ---------------------------------------------------------
with tab1:
    st.header("Resultados Consolidados")
    
    # Cargar todos los datos registrados
    df = pd.read_sql_query("SELECT * FROM actas", conn)
    
    if not df.empty:
        # Sumas automáticas directas
        total_partido_1 = df['votos_partido_1'].sum()
        total_partido_2 = df['votos_partido_2'].sum()
        total_blancos = df['votos_blancos'].sum()
        total_nulos = df['votos_nulos'].sum()
        total_mesas = len(df)

        # Muestras visuales en tarjetas (Metrics)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Partido 1", f"{total_partido_1:,}")
        col2.metric("Partido 2", f"{total_partido_2:,}")
        col3.metric("Blancos / Nulos", f"{total_blancos + total_nulos:,}")
        col4.metric("Mesas Procesadas", total_mesas)

        st.markdown("---")
        st.subheader("Tabla General de Mesas")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Aún no se han registrado actas en el sistema.")

# ---------------------------------------------------------
# PESTAÑA 2: DETALLE Y CONTEO POR NUMERO DE MESA
# ---------------------------------------------------------
with tab2:
    st.header("Buscar Conteo de una Mesa")
    
    # Obtener lista de mesas registradas para el menú desplegable
    mesas_disponibles = pd.read_sql_query("SELECT numero_mesa FROM actas", conn)['numero_mesa'].tolist()
    
    if mesas_disponibles:
        # Selector interactivo o ingreso de texto
        mesa_seleccionada = st.selectbox("Selecciona o busca el número de mesa:", mesas_disponibles)
        
        if mesa_seleccionada:
            c.execute("SELECT * FROM actas WHERE numero_mesa = ?", (mesa_seleccionada,))
            acta = c.fetchone()
            
            if acta:
                st.success(f"📌 Detalle de Conteo para la Mesa N° {acta[0]}")
                
                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("Votos Partido 1", acta[1])
                m_col2.metric("Votos Partido 2", acta[2])
                m_col3.metric("Blancos / Nulos", acta[3] + acta[4])
                
                st.caption(f"Registrado el: {acta[5]}")
    else:
        st.warning("No hay mesas registradas para consultar.")
