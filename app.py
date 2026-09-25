import base64
from datetime import datetime
import ipaddress
import os
import platform
import socket
import subprocess
import sqlite3
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# Page configuration
st.set_page_config(
    page_title="Cement Industries (Sabah) - IT Helpdesk",
    page_icon="🏢",
    layout="wide",
)

# --- DATABASE SETUP ---
DB_FILE = "it_helpdesk.db"


def init_db():
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()

  # Tickets Table
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            plant_section TEXT NOT NULL,
            issue TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

  # Audit Trail Table
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            action TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

  # Users Table for RBAC
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            department TEXT NOT NULL
        )
    """)

  # IPAM Table for Plant Industrial Asset Tracking
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS ipam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL
        )
    """)

  # AnyDesk Remote Stations Directory Table
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS anydesk_directory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_name TEXT NOT NULL,
            anydesk_id TEXT NOT NULL,
            location TEXT NOT NULL,
            department TEXT NOT NULL
        )
    """)

  # Plant Departments Table
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

  # Ticket Live Chat Messages Table
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticket_chats (
            chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id)
        )
    """)

  # Seed default admin user only if users table is completely empty
  cursor.execute("SELECT COUNT(*) FROM users")
  if cursor.fetchone()[0] == 0:
    default_users = [
        ("admin", "admin123", "Admin", "IT Infrastructure (Kota Kinabalu)"),
        ("plant_user", "plant123", "Staff", "Plant Operations / Production"),
    ]
    cursor.executemany(
        "INSERT INTO users (username, password, role, department) VALUES (?, ?,"
        " ?, ?)",
        default_users,
    )

  conn.commit()
  conn.close()


init_db()


# Database helper functions with Role-Based Backend Filtering
def load_tickets(role, username):
  conn = sqlite3.connect(DB_FILE)
  if role == "Admin":
    df = pd.read_sql_query("SELECT * FROM tickets", conn)
  else:
    df = pd.read_sql_query(
        "SELECT * FROM tickets WHERE LOWER(name) = LOWER(?)",
        conn,
        params=(username,),
    )
  conn.close()
  if not df.empty:
    df = df.rename(
        columns={
            "id": "Ticket ID",
            "name": "Operator Name",
            "plant_section": "Plant Section",
            "issue": "Issue Description",
            "status": "Status",
            "created_at": "Created At",
        }
    )
  return df


def load_audit_logs():
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query(
      "SELECT * FROM audit_logs ORDER BY timestamp DESC", conn
  )
  conn.close()
  if not df.empty:
    df = df.rename(
        columns={
            "log_id": "Log ID",
            "ticket_id": "Ticket ID",
            "action": "Action Logged",
            "timestamp": "Timestamp",
        }
    )
  return df


def load_ipam():
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query("SELECT * FROM ipam", conn)
  conn.close()
  if not df.empty:
    df = df.rename(
        columns={
            "id": "Asset ID",
            "device_name": "Device Name",
            "ip_address": "IP Address",
            "category": "Category",
            "location": "Location",
        }
    )
  return df


def load_anydesk():
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query("SELECT * FROM anydesk_directory", conn)
  conn.close()
  if not df.empty:
    df = df.rename(
        columns={
            "id": "Directory ID",
            "station_name": "Station Name",
            "anydesk_id": "AnyDesk ID / Alias",
            "location": "Location",
            "department": "Department",
        }
    )
  return df


def load_departments():
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  cursor.execute("SELECT name FROM departments ORDER BY name ASC")
  depts = [row[0] for row in cursor.fetchall()]
  conn.close()
  return depts


def load_users():
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query(
      "SELECT username, role, department FROM users", conn
  )
  conn.close()
  if not df.empty:
    df = df.rename(
        columns={
            "username": "Username",
            "role": "Role",
            "department": "Department",
        }
    )
  return df


def load_ticket_chats(ticket_id):
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query(
      "SELECT * FROM ticket_chats WHERE ticket_id = ? ORDER BY timestamp ASC",
      conn,
      params=(ticket_id,),
  )
  conn.close()
  return df


def log_action(ticket_id, action):
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  cursor.execute(
      "INSERT INTO audit_logs (ticket_id, action, timestamp) VALUES (?, ?, ?)",
      (ticket_id, action, timestamp),
  )
  conn.commit()
  conn.close()


def authenticate(username, password):
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT role, department FROM users WHERE username = ? AND password = ?",
      (username, password),
  )
  user = cursor.fetchone()
  conn.close()
  return user


def get_weather():
  try:
    res = requests.get(
        "https://wttr.in/Kota+Kinabalu?format=%c+%t+(%C)", timeout=2
    )
    if res.status_code == 200:
      return res.text.strip()
  except Exception:
    pass
  return "🌤️ 31°C (Sepangar Bay)"


def ping_host(host):
  param = "-n" if platform.system().lower() == "windows" else "-c"
  command = ["ping", param, "1", host]
  try:
    output = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=3,
    )
    return output.returncode == 0, output.stdout
  except subprocess.TimeoutExpired:
    return False, "Ping request timed out."
  except Exception as e:
    return False, str(e)


def scan_port(host, port):
  try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    result = sock.connect_ex((host, int(port)))
    sock.close()
    return result == 0
  except Exception:
    return False


# --- SESSION STATE INITIALIZATION ---
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
  st.session_state.username = ""
  st.session_state.role = ""
  st.session_state.department = ""

# --- CUSTOM STYLING ---


def set_bg_image(image_file):
  if os.path.exists(image_file):
    with open(image_file, "rb") as f:
      encoded = base64.b64encode(f.read()).decode()
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: linear-gradient(rgba(11, 15, 25, 0.85), rgba(11, 15, 25, 0.90)), url("data:image/jpeg;base64,{encoded}");
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


set_bg_image("sabah_cement.jpg")

st.markdown(
    """
    <style>
        h1, h2, h3 { font-weight: 800; letter-spacing: -0.5px; color: #ffffff; }
        div[data-testid="stMetric"] {
            background-color: rgba(17, 24, 39, 0.85);
            border: 1px solid #1f2937;
            padding: 15px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        div[data-testid="stMetric"] label { color: #9ca3af !important; font-weight: 600; }
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #60a5fa; font-weight: 700; }
        .stButton>button { width: 100%; border-radius: 8px; font-weight: 600; background-color: #3b82f6; color: white; border: none; transition: all 0.2s; }
        .stButton>button:hover { background-color: #2563eb; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4); }
        [data-testid="stSidebar"] { background-color: rgba(15, 23, 42, 0.95); border-right: 1px solid #1e293b; }
    </style>
""",
    unsafe_allow_html=True,
)

# --- AUTHENTICATION SCREEN ---
if not st.session_state.logged_in:
  col_l1, col_l2 = st.columns([1, 1])
  with col_l1:
    st.markdown(
        """
        <div style="background: rgba(15, 23, 42, 0.75); padding: 30px; border-radius: 16px; border: 1px solid #334155; text-align: center; margin-top: 40px;">
            <h2 style="color: #ffffff; margin-bottom: 10px;">Cement Industries (Sabah)</h2>
            <p style="color: #93c5fd; font-weight: 500;">Sepangar Bay Grinding Plant • Kota Kinabalu</p>
            <hr style="border-color: #334155; margin: 20px 0;">
            <p style="color: #cbd5e1; font-size: 0.95rem;">Centralized IT Helpdesk Portal & Industrial Asset Management.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
  with col_l2:
    st.title("🏢 Cement Industries (Sabah) Sdn Bhd")
    st.markdown("### **IT Helpdesk**")
    st.caption("Sepangar Bay Grinding Plant • Kota Kinabalu, Sabah")
    st.markdown("---")

    with st.form("login_form"):
      st.subheader("Secure Operator Sign In")
      username_input = st.text_input("Username")
      password_input = st.text_input("Password", type="password")
      login_btn = st.form_submit_button("Authenticate Access")

      if login_btn:
        user_data = authenticate(username_input, password_input)
        if user_data:
          st.session_state.logged_in = True
          st.session_state.username = username_input
          st.session_state.role = user_data[0]
          st.session_state.department = user_data[1]
          st.success("Authentication successful!")
          st.rerun()
        else:
          st.error("Invalid operator credentials.")

    
  st.stop()

# --- MAIN DASHBOARD ---
df_tickets = load_tickets(st.session_state.role, st.session_state.username)

weather_info = get_weather()
banner_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ margin: 0; background-color: transparent; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .plant-banner {{
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.9) 100%);
            border: 1px solid #334155; padding: 20px; border-radius: 12px;
            display: flex; justify-content: space-between; align-items: center; box-sizing: border-box; width: 100%;
        }}
    </style>
</head>
<body>
    <div class="plant-banner">
        <div>
            <h2 style="margin:0; font-size: 1.5rem; color: #ffffff; font-weight: 800;">🏢 Cement Industries (Sabah) Sdn Bhd</h2>
            <p style="margin:4px 0 0 0; color: #93c5fd; font-weight: 500; font-size: 0.95rem;">IT Helpdesk • Sepangar Bay Facility</p>
        </div>
        <div style="text-align: right; color: #e2e8f0; font-family: monospace; background: rgba(15, 23, 42, 0.7); padding: 10px 15px; border-radius: 8px; border: 1px solid #334155;">
            <div id="live-clock" style="font-size: 1.15rem; font-weight: bold; color: #60a5fa;">Loading...</div>
            <div style="font-size: 0.85rem; margin-top: 4px; color: #cbd5e1;">{weather_info}</div>
        </div>
    </div>
    <script>
        function updateClock() {{
            const now = new Date();
            const options = {{ timeZone: 'Asia/Kuala_Lumpur', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }};
            document.getElementById('live-clock').innerText = now.toLocaleTimeString('en-US', options);
        }}
        setInterval(updateClock, 1000);
        updateClock();
    </script>
</body>
</html>
"""
components.html(banner_html, height=105)

col_info, col_logout = st.columns([4, 1])
with col_info:
  st.success(
      f"Operator: **{st.session_state.username.upper()}** | Role:"
      f" **{st.session_state.role}** | Department:"
      f" **{st.session_state.department}**"
  )
with col_logout:
  if st.button("Log Out"):
    st.session_state.logged_in = False
    st.rerun()

st.markdown("---")

# --- METRIC CARDS ---
col1, col2, col3, col4 = st.columns(4)
total_tickets = len(df_tickets)
open_tickets = (
    len(df_tickets[df_tickets["Status"] == "Open"])
    if not df_tickets.empty
    else 0
)
progress_tickets = (
    len(df_tickets[df_tickets["Status"] == "In Progress"])
    if not df_tickets.empty
    else 0
)
resolved_tickets = (
    len(df_tickets[df_tickets["Status"] == "Resolved"])
    if not df_tickets.empty
    else 0
)

col1.metric("📊 Total Incidents", total_tickets)
col2.metric("🚨 Critical Open", open_tickets)
col3.metric("⏳ In Progress", progress_tickets)
col4.metric("✅ Resolved", resolved_tickets)

st.markdown("---")

# --- SIDEBAR: TICKET SUBMISSION & CHAT ---
st.sidebar.header("📝 Raise Plant IT Ticket")
departments_list = load_departments()

with st.sidebar.form("ticket_form", clear_on_submit=True):
  name = st.text_input(
      "Operator Name", value=f"{st.session_state.username.upper()}"
  )
  plant_section = st.selectbox(
      "Plant Section / Department",
      departments_list if departments_list else ["General"],
  )
  issue = st.text_area(
      "Incident Description / Fault Details",
      placeholder=(
          "e.g., SCADA terminal losing connection to PLC gateway..."
      ),
  )
  submit = st.form_submit_button("Transmit Ticket")

  if submit and name and issue:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO tickets (name, plant_section, issue, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, plant_section, issue, "Open", timestamp),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    log_action(
        new_id,
        f"Incident ticket raised by {st.session_state.username}"
        f" ({plant_section})",
    )
    st.sidebar.success(f"Incident Ticket #{new_id} transmitted successfully!")
    st.rerun()
  elif submit:
    st.sidebar.error("Please fill in all required fields.")

st.sidebar.markdown("---")
with st.sidebar.expander("💬 Live IT Support Chat Drawer", expanded=True):
  if df_tickets.empty:
    st.caption("No active tickets to chat about.")
  else:
    chat_ticket_id = st.selectbox(
        "Select Ticket ID", df_tickets["Ticket ID"].tolist(), key="sidebar_chat_id"
    )

    df_chats = load_ticket_chats(chat_ticket_id)
    chat_box = st.container(height=200)
    with chat_box:
      if df_chats.empty:
        st.caption("Send a direct message to IT for this ticket.")
      else:
        for _, chat in df_chats.iterrows():
          is_me = chat["sender"] == st.session_state.username
          align = "right" if is_me else "left"
          bg_color = "#1e3a8a" if is_me else "#374151"
          st.markdown(
              f"""
                    <div style="text-align: {align}; margin-bottom: 6px;">
                        <span style="font-size: 0.65rem; color: #9ca3af;">{chat['sender']} ({chat['timestamp'][11:16]})</span>
                        <div style="background-color: {bg_color}; color: white; padding: 5px 8px; border-radius: 6px; display: inline-block; max-width: 95%; font-size: 0.8rem; text-align: left;">
                            {chat['message']}
                        </div>
                    </div>
                    """,
              unsafe_allow_html=True,
          )

    with st.form(f"sidebar_chat_form_{chat_ticket_id}", clear_on_submit=True):
      sidebar_msg = st.text_input(
          "Type message...",
          placeholder="Type here...",
          label_visibility="collapsed",
      )
      if st.form_submit_button("Send"):
        if sidebar_msg:
          conn = sqlite3.connect(DB_FILE)
          cursor = conn.cursor()
          timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
          cursor.execute(
              "INSERT INTO ticket_chats (ticket_id, sender, role, message,"
              " timestamp) VALUES (?, ?, ?, ?, ?)",
              (
                  chat_ticket_id,
                  st.session_state.username,
                  st.session_state.role,
                  sidebar_msg,
                  timestamp,
              ),
          )
          conn.commit()
          conn.close()
          st.rerun()

    if st.session_state.role == "Admin":
      if st.button("🗑️ Clear Chat History for Ticket", key="clear_chat_btn"):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM ticket_chats WHERE ticket_id = ?", (chat_ticket_id,)
        )
        conn.commit()
        conn.close()
        st.success(
            f"Chat history cleared for Ticket #{chat_ticket_id} successfully!"
        )
        st.rerun()


# --- MAIN TABS BASED ON ROLE ---
if st.session_state.role == "Admin":
  tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
      "📋 Plant Incident Registry",
      "📜 Immutable Audit Trail",
      "🌐 Network Diagnostics",
      "🗺️ Plant IPAM & AnyDesk Directory",
      "🏢 Department Management",
      "👥 User Access Management",
      "📹 Hikvision CCTV Hub",
  ])
else:
  tab1 = st.container()

with tab1:
  active_tab, closed_tab = st.tabs([
      "🟢 Active Incidents",
      "📁 Closed & Previous Tickets",
  ])

  with active_tab:
    st.subheader("Active Plant Incidents")
    if df_tickets.empty:
      st.info("No active incidents logged in the plant database.")
    else:
      df_active = df_tickets[df_tickets["Status"] != "Closed"]

      if df_active.empty:
        st.info("No active incidents right now. All tickets are closed.")
      else:
        st.dataframe(df_active, use_container_width=True, height=300)

      if st.session_state.role == "Admin":
        st.markdown("---")
        col_left, col_right = st.columns([1, 1])
        with col_left:
          st.subheader("⚙️ Update Incident Workflow")
          with st.form("update_form"):
            ticket_ids = df_tickets["Ticket ID"].tolist()
            selected_id = st.selectbox(
                "Select Incident ID to Update", ticket_ids
            )
            new_status = st.selectbox(
                "Resolution Status",
                ["Open", "In Progress", "Resolved", "Closed"],
            )
            update_submit = st.form_submit_button("Commit Workflow State")

            if update_submit:
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()
              cursor.execute(
                  "UPDATE tickets SET status = ? WHERE id = ?",
                  (new_status, selected_id),
              )
              conn.commit()
              conn.close()

              log_action(
                  selected_id,
                  f"Incident #{selected_id} status changed to '{new_status}' by"
                  f" Admin {st.session_state.username}",
              )
              st.success(f"Incident #{selected_id} updated to **{new_status}**")
              st.rerun()

          st.markdown("---")
          with st.form("delete_all_tickets_form"):
            st.markdown("#### ⚠️ Danger Zone: Bulk Ticket Operations")
            del_all_tickets_btn = st.form_submit_button(
                "🗑️ Delete All Tickets & History"
            )
            if del_all_tickets_btn:
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()
              cursor.execute("DELETE FROM tickets")
              cursor.execute("DELETE FROM ticket_chats")
              conn.commit()
              conn.close()
              st.success("All tickets and related chats deleted successfully!")
              st.rerun()

        with col_right:
          st.subheader("💡 Enterprise Compliance")
          st.markdown(
              "> All state changes, asset modifications, and diagnostics are"
              " securely committed to local storage for operational auditing"
              " and compliance tracking across CIS facilities."
          )

  with closed_tab:
    st.subheader("📁 Closed & Previous Ticket Archive")
    if df_tickets.empty:
      st.info("No archive records found.")
    else:
      df_closed = df_tickets[df_tickets["Status"] == "Closed"]
      if df_closed.empty:
        st.info("No closed tickets yet.")
      else:
        st.dataframe(df_closed, use_container_width=True, height=300)

if st.session_state.role == "Admin":
  with tab2:
    st.subheader("Immutable System Audit Trail")
    df_audit = load_audit_logs()
    if df_audit.empty:
      st.info("No audit logs recorded yet.")
    else:
      st.dataframe(df_audit, use_container_width=True, height=300)
      st.markdown("---")
      with st.form("clear_audit_form"):
        clear_audit_btn = st.form_submit_button("🗑️ Delete All Audit Logs")
        if clear_audit_btn:
          conn = sqlite3.connect(DB_FILE)
          cursor = conn.cursor()
          cursor.execute("DELETE FROM audit_logs")
          conn.commit()
          conn.close()
          st.success("All audit logs deleted successfully!")
          st.rerun()

  with tab3:
    st.subheader("🌐 Industrial Network Diagnostics & Remote Access")
    col_net1, col_net2 = st.columns(2)

    with col_net1:
      st.markdown("### **PLC / Gateway ICMP Ping**")
      target_host = st.text_input(
          "Target Device IP Address", value="192.168.10.10", key="ping_host"
      )
      if st.button("Run Plant Ping Test"):
        with st.spinner(f"Pinging industrial node {target_host}..."):
          is_online, response_output = ping_host(target_host)
          if is_online:
            st.success(f"Node {target_host} is ONLINE & Responsive!")
          else:
            st.error(f"Node {target_host} is UNREACHABLE / Connection Lost.")
          with st.expander("View Terminal Output"):
            st.code(response_output)

      st.markdown("---")
      st.markdown("### **Industrial Port Availability Check**")
      scan_target = st.text_input(
          "Target IP for Port Scan",
          value="192.168.10.10",
          key="port_scan_host",
      )
      scan_port_num = st.number_input(
          "Port Number (e.g. 502 for Modbus / 80 for HMI)",
          min_value=1,
          max_value=65535,
          value=502,
      )
      if st.button("Scan Industrial Port"):
        with st.spinner(f"Scanning port {scan_port_num} on {scan_target}..."):
          is_open = scan_port(scan_target, scan_port_num)
          if is_open:
            st.success(
                f"Port {scan_port_num} on {scan_target} is ACTIVE & LISTENING!"
            )
          else:
            st.error(f"Port {scan_port_num} on {scan_target} is CLOSED.")

    with col_net2:
      st.markdown("### **Quick AnyDesk Station Launcher**")
      df_anydesk_quick = load_anydesk()
      if not df_anydesk_quick.empty:
        df_anydesk_quick["Display_Label"] = (
            df_anydesk_quick["Station Name"]
            + " ("
            + df_anydesk_quick["AnyDesk ID / Alias"]
            + " - "
            + df_anydesk_quick["Location"]
            + ")"
        )
        selected_display = st.selectbox(
            "Select Registered Plant Station",
            df_anydesk_quick["Display_Label"].tolist(),
        )
        station_row = df_anydesk_quick[
            df_anydesk_quick["Display_Label"] == selected_display
        ].iloc[0]
        anydesk_target_id = station_row["AnyDesk ID / Alias"]
        st.caption(
            f"Target ID: `{anydesk_target_id}` | Location:"
            f" {station_row['Location']}"
        )
      else:
        anydesk_target_id = ""
        st.info("No AnyDesk stations registered in directory yet.")

      st.markdown("<br>", unsafe_allow_html=True)
      st.markdown(
          f"""
            <a href="anydesk:{anydesk_target_id}" target="_blank" style="text-decoration: none;">
                <button style="
                    width: 100%;
                    background-color: #ef4444;
                    color: white;
                    padding: 0.6rem 1rem;
                    border: none;
                    border-radius: 8px;
                    font-weight: 600;
                    cursor: pointer;
                    text-align: center;
                ">
                    🚀 Launch Selected AnyDesk Remote Session
                </button>
            </a>
        """,
          unsafe_allow_html=True,
      )

  with tab4:
    st.subheader("🗺️ Plant IPAM & AnyDesk Network Directory")

    net_tab1, net_tab2, net_tab3 = st.tabs([
        "📋 Static IP Registry",
        "🚀 AnyDesk Directory",
        "🧮 Subnet Calculator",
    ])

    with net_tab1:
      st.markdown("### **Static IP Allocations (Industrial Network)**")
      df_ipam = load_ipam()
      if df_ipam.empty:
        st.info("No static IP assets registered.")
      else:
        st.dataframe(df_ipam, use_container_width=True)

      col_ip_del, col_ip_add = st.columns(2)
      with col_ip_del:
        with st.form("delete_ipam_form"):
          st.markdown("#### Remove Static IP Asset")
          if not df_ipam.empty:
            del_ip_id = st.selectbox(
                "Select Asset ID to Remove", df_ipam["Asset ID"].tolist()
            )
            del_ip_btn = st.form_submit_button("Delete IP Asset")
            if del_ip_btn:
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()
              cursor.execute("DELETE FROM ipam WHERE id = ?", (del_ip_id,))
              conn.commit()
              conn.close()
              st.success(f"Asset ID #{del_ip_id} removed successfully!")
              st.rerun()
          else:
            st.caption("No assets available to delete.")
            st.form_submit_button("Delete IP Asset", disabled=True)

        st.markdown("---")
        with st.form("delete_all_ipam_form"):
          del_all_ip_btn = st.form_submit_button("🗑️ Delete All IP Assets")
          if del_all_ip_btn:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ipam")
            conn.commit()
            conn.close()
            st.success("All IP assets deleted successfully!")
            st.rerun()

      with col_ip_add:
        with st.form("add_ipam_form"):
          st.markdown("#### Register New Static IP Asset")
          new_dev = st.text_input(
              "Device Name", placeholder="e.g. Packer Line 2 HMI"
          )
          new_ip = st.text_input("IP Address", placeholder="e.g. 192.168.10.55")
          new_cat = st.text_input(
              "Category", placeholder="e.g. Industrial PLC"
          )
          new_loc = st.text_input(
              "Plant Location", placeholder="e.g. Packing Bay B"
          )
          add_ip_btn = st.form_submit_button("Commit IP Asset")
          if add_ip_btn and new_dev and new_ip:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ipam (device_name, ip_address, category, location)"
                " VALUES (?, ?, ?, ?)",
                (new_dev, new_ip, new_cat, new_loc),
            )
            conn.commit()
            conn.close()
            st.success(f"Registered **{new_dev}** (`{new_ip}`) successfully!")
            st.rerun()

    with net_tab2:
      st.markdown("### **AnyDesk Remote Workstation Directory**")
      df_anydesk = load_anydesk()
      if df_anydesk.empty:
        st.info("No AnyDesk stations registered.")
      else:
        st.dataframe(df_anydesk, use_container_width=True)

      col_ad_del, col_ad_add = st.columns(2)
      with col_ad_del:
        with st.form("delete_anydesk_form"):
          st.markdown("#### Remove AnyDesk Station")
          if not df_anydesk.empty:
            del_ad_id = st.selectbox(
                "Select Directory ID to Remove",
                df_anydesk["Directory ID"].tolist(),
            )
            del_ad_btn = st.form_submit_button("Delete Station Record")
            if del_ad_btn:
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()
              cursor.execute(
                  "DELETE FROM anydesk_directory WHERE id = ?", (del_ad_id,)
              )
              conn.commit()
              conn.close()
              st.success(f"Station record #{del_ad_id} deleted!")
              st.rerun()
          else:
            st.caption("No records available.")
            st.form_submit_button("Delete Station Record", disabled=True)

        st.markdown("---")
        with st.form("delete_all_anydesk_form"):
          del_all_ad_btn = st.form_submit_button(
              "🗑️ Delete All AnyDesk Stations"
          )
          if del_all_ad_btn:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM anydesk_directory")
            conn.commit()
            conn.close()
            st.success("All AnyDesk station records deleted successfully!")
            st.rerun()

      with col_ad_add:
        with st.form("add_anydesk_form"):
          st.markdown("#### Register AnyDesk Workstation")
          new_st_name = st.text_input(
              "Station Name", placeholder="e.g. Kiln Terminal 2"
          )
          new_ad_id = st.text_input(
              "AnyDesk ID / Alias", placeholder="e.g. 992810471@ad"
          )
          new_st_loc = st.text_input(
              "Location", placeholder="e.g. Kiln Control Room"
          )
          new_st_dept = st.selectbox(
              "Department",
              departments_list if departments_list else ["General"],
          )
          add_ad_btn = st.form_submit_button("Commit AnyDesk Record")
          if add_ad_btn and new_st_name and new_ad_id:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO anydesk_directory (station_name, anydesk_id,"
                " location, department) VALUES (?, ?, ?, ?)",
                (new_st_name, new_ad_id, new_st_loc, new_st_dept),
            )
            conn.commit()
            conn.close()
            st.success(f"Registered **{new_st_name}** successfully!")
            st.rerun()

    with net_tab3:
      st.markdown("### **Plant Subnet & CIDR Calculator**")
      cidr_input = st.text_input(
          "Enter Plant Subnet Block",
          value="192.168.10.0/24",
          placeholder="e.g. 192.168.10.0/24",
      )
      if st.button("Calculate Subnet Layout"):
        try:
          network = ipaddress.ip_network(cidr_input, strict=False)
          col_c1, col_c2, col_c3 = st.columns(3)
          col_c1.metric("Network Address", str(network.network_address))
          col_c2.metric("Broadcast Address", str(network.broadcast_address))
          col_c3.metric("Usable Host Capacity", network.num_addresses - 2)
          st.markdown("#### Configuration Specs:")
          st.code(
              f"Subnet Mask: {network.netmask}\nFirst Usable IP:"
              f" {list(network.hosts())[0] if network.num_addresses > 2 else 'N/A'}\nLast"
              f" Usable IP:"
              f" {list(network.hosts())[-1] if network.num_addresses > 2 else 'N/A'}"
          )
        except Exception as e:
          st.error(f"Invalid CIDR notation: {e}")

  with tab5:
    st.subheader("🏢 Plant Department & Section Management")
    st.markdown(
        "Add or remove departments and plant sections dynamically. Any changes"
        " will immediately update the ticket submission forms."
    )

    current_depts = load_departments()
    col_d1, col_d2 = st.columns(2)

    with col_d1:
      st.markdown("### **Current Departments / Plant Sections**")
      if not current_depts:
        st.info("No departments registered.")
      else:
        for d in current_depts:
          st.markdown(f"- 🏢 `{d}`")

    with col_d2:
      st.markdown("### **Manage Departments**")
      with st.form("add_dept_form"):
        new_dept_name = st.text_input(
            "New Department / Section Name",
            placeholder="e.g., Electrical Maintenance",
        )
        add_dept_btn = st.form_submit_button("Add Department")
        if add_dept_btn and new_dept_name:
          try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO departments (name) VALUES (?)",
                (new_dept_name.strip(),),
            )
            conn.commit()
            conn.close()
            st.success(
                f"Department **{new_dept_name}** added successfully!"
            )
            st.rerun()
          except sqlite3.IntegrityError:
            st.error("This department already exists.")

      st.markdown("---")
      with st.form("remove_dept_form"):
        if current_depts:
          rem_dept = st.selectbox(
              "Select Department to Remove", current_depts
          )
          rem_dept_btn = st.form_submit_button("Remove Department")
          if rem_dept_btn:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM departments WHERE name = ?", (rem_dept,)
            )
            conn.commit()
            conn.close()
            st.success(f"Department **{rem_dept}** removed successfully!")
            st.rerun()
        else:
          st.caption("No departments available.")
          st.form_submit_button("Remove Department", disabled=True)

      st.markdown("---")
      with st.form("delete_all_depts_form"):
        del_all_depts_btn = st.form_submit_button("🗑️ Delete All Departments")
        if del_all_depts_btn:
          conn = sqlite3.connect(DB_FILE)
          cursor = conn.cursor()
          cursor.execute("DELETE FROM departments")
          conn.commit()
          conn.close()
          st.success("All departments deleted successfully!")
          st.rerun()

  with tab6:
    st.subheader("👥 User Access & Role Management")
    st.markdown(
        "Register new system operators or revoke access credentials for plant"
        " staff and IT administrators."
    )

    df_users = load_users()
    col_u1, col_u2 = st.columns(2)

    with col_u1:
      st.markdown("### **Registered System Users**")
      if df_users.empty:
        st.info("No users found.")
      else:
        st.dataframe(df_users, use_container_width=True)

      st.markdown("---")
      with st.form("remove_user_form"):
        st.markdown("#### Revoke User Access")
        if not df_users.empty:
          # Prevent deleting default admin if desired, or allow with caution
          users_list = df_users["Username"].tolist()
          rem_username = st.selectbox("Select Username to Remove", users_list)
          rem_user_btn = st.form_submit_button("Revoke User")
          if rem_user_btn:
            if rem_username == "admin":
              st.error("Cannot delete the primary administrator account!")
            else:
              conn = sqlite3.connect(DB_FILE)
              cursor = conn.cursor()
              cursor.execute(
                  "DELETE FROM users WHERE username = ?", (rem_username,)
              )
              conn.commit()
              conn.close()
              st.success(
                  f"User account **{rem_username}** deleted successfully!"
              )
              st.rerun()
        else:
          st.caption("No users to remove.")
          st.form_submit_button("Revoke User", disabled=True)

    with col_u2:
      st.markdown("### **Register New Operator Account**")
      with st.form("add_user_form"):
        new_username = st.text_input(
            "Username", placeholder="e.g. hafiz_it or operator2"
        )
        new_password = st.text_input(
            "Password", type="password", placeholder="Enter initial password"
        )
        new_role = st.selectbox("Role Assignment", ["Staff", "Admin"])
        new_user_dept = st.selectbox(
            "Department Assignment",
            departments_list if departments_list else ["General"],
            key="new_user_dept_select",
        )

        add_user_btn = st.form_submit_button("Create Operator Account")
        if add_user_btn and new_username and new_password:
          try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password, role, department)"
                " VALUES (?, ?, ?, ?)",
                (
                    new_username.strip(),
                    new_password,
                    new_role,
                    new_user_dept,
                ),
            )
            conn.commit()
            conn.close()
            st.success(
                f"Account for **{new_username}** created successfully with"
                f" role **{new_role}**!"
            )
            st.rerun()
          except sqlite3.IntegrityError:
            st.error(
                "A user with this username already exists. Choose a different"
                " username."
            )

    st.markdown("---")
    st.markdown("### **Update User Password**")
    with st.form("change_password_form"):
      if not df_users.empty:
        target_user = st.selectbox("Select User to Update Password", df_users["Username"].tolist(), key="change_pwd_user")
      else:
        target_user = st.text_input("Username", key="change_pwd_user_text")
      
      new_pwd_input = st.text_input("New Password", type="password", key="new_pwd_input")
      confirm_pwd_input = st.text_input("Confirm New Password", type="password", key="confirm_pwd_input")
      
      update_pwd_btn = st.form_submit_button("Update Password")
      if update_pwd_btn:
        if not new_pwd_input or not confirm_pwd_input:
          st.error("Please fill in all password fields.")
        elif new_pwd_input != confirm_pwd_input:
          st.error("New passwords do not match!")
        elif target_user:
          try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET password = ? WHERE username = ?",
                (new_pwd_input, target_user),
            )
            conn.commit()
            conn.close()
            st.success(f"Password for **{target_user}** updated successfully!")
            st.rerun()
          except Exception as e:
            st.error(f"Error updating password: {e}")
        else:
          st.error("Please specify a valid user.")

  with tab7:
    st.subheader("📹 Hikvision NVR & Plant Surveillance Hub")
    st.markdown(
        "Direct web shortcuts and stream channels for the facility's"
        " Hikvision security system."
    )

    col_h1, col_h2 = st.columns(2)

    with col_h1:
      st.markdown("### **NVR Network Configuration**")
      nvr_ip = st.text_input(
          "Hikvision NVR Local IP Address",
          value="192.168.10.200",
          help="Enter the local static IP of your Hikvision NVR.",
      )
      nvr_port = st.text_input(
          "Web Port", value="80", help="Standard HTTP port is usually 80 or 85."
      )

      nvr_base_url = f"http://{nvr_ip}:{nvr_port}"

      st.markdown("<br>", unsafe_allow_html=True)
      st.markdown(
          f"""
                <a href="{nvr_base_url}" target="_blank" style="text-decoration: none;">
                    <button style="
                        width: 100%;
                        background-color: #0284c7;
                        color: white;
                        padding: 0.75rem 1rem;
                        border: none;
                        border-radius: 8px;
                        font-weight: 600;
                        cursor: pointer;
                        text-align: center;
                    ">
                        🌐 Open Hikvision NVR Web Console
                    </button>
                </a>
            """,
          unsafe_allow_html=True,
      )

      st.markdown("---")
      st.markdown("### **Quick Camera Channel Shortcuts**")
      cam_channel = st.selectbox(
          "Select Plant Zone / Channel",
          [
              "Channel 1 - Main Guardhouse / Gate",
              "Channel 2 - Raw Material Yard",
              "Channel 3 - Kiln & Production Line",
              "Channel 4 - Packing Plant & Loading Bay",
              "Channel 5 - Admin Office Corridor",
          ],
      )

      st.markdown(
          f"""
                <a href="{nvr_base_url}/lyd/index.html" target="_blank" style="text-decoration: none;">
                    <button style="
                        width: 100%;
                        background-color: #059669;
                        color: white;
                        padding: 0.6rem 1rem;
                        border: none;
                        border-radius: 8px;
                        font-weight: 600;
                        cursor: pointer;
                        text-align: center;
                    ">
                        🎥 Launch Live View ({cam_channel})
                    </button>
                </a>
            """,
          unsafe_allow_html=True,
      )

    with col_h2:
      st.markdown("### **Quick Diagnostics for Camera Network**")
      st.markdown(
          "If a camera feed goes offline, you can quickly verify its reachability"
          " via ICMP ping right from the helpdesk."
      )

      cam_test_ip = st.text_input(
          "Camera IP to Test",
          value="192.168.10.201",
          key="cam_ping_target",
      )
      if st.button("Ping Camera Node"):
        with st.spinner(f"Checking camera at {cam_test_ip}..."):
          is_alive, output = ping_host(cam_test_ip)
          if is_alive:
            st.success(f"Camera node {cam_test_ip} is responding normally.")
          else:
            st.error(
                f"Camera node {cam_test_ip} is offline or unreachable. Check"
                " PoE switch."
            )
          with st.expander("Ping Log"):
            st.code(output)

      st.info(
          "💡 **Tip:** Modern Hikvision web management interfaces work best on"
          " browsers like Microsoft Edge or Google Chrome. Depending on"
          " firmware version, plugins may be required for live plugin-heavy"
          " views, though newer HTML5-based firmwares open streams directly."
      )
