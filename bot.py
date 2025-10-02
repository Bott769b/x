import os
import logging
import asyncio
import paramiko
import json
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ===== KONFIGURASI =====
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [123456789]  # Ganti dengan ID Telegram Anda

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load konfigurasi Windows
try:
    with open('windows_config.json', 'r') as f:
        WINDOWS_CONFIG = json.load(f)
except Exception as e:
    logger.error(f"Error loading config: {e}")
    WINDOWS_CONFIG = {
        "server_2019": {
            "name": "Windows Server 2019",
            "script": "netboot",
            "size": "10GB",
            "notes": "Standard Edition"
        },
        "server_2022": {
            "name": "Windows Server 2022",
            "script": "netboot", 
            "size": "12GB",
            "notes": "Standard Edition"
        },
        "win_10": {
            "name": "Windows 10 Pro",
            "script": "netboot",
            "size": "8GB", 
            "notes": "22H2 Version"
        },
        "win_11": {
            "name": "Windows 11 Pro",
            "script": "netboot",
            "size": "9GB",
            "notes": "23H2 Version"
        }
    }

# ===== KELAS INSTALLER =====
class RDPInstaller:
    def __init__(self):
        self.active_installations = {}
    
    async def connect_ssh(self, host, username, password, port=22):
        """Koneksi SSH ke VPS"""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port, username, password, timeout=30)
            return client
        except Exception as e:
            raise Exception(f"❌ Gagal koneksi SSH: {str(e)}")
    
    async def check_vps_specs(self, ssh, progress_callback):
        """Cek spesifikasi VPS"""
        try:
            # Cek RAM
            stdin, stdout, stderr = ssh.exec_command("free -h | grep Mem:")
            ram_info = stdout.read().decode().strip()
            
            # Cek Disk
            stdin, stdout, stderr = ssh.exec_command("df -h / | tail -1")
            disk_info = stdout.read().decode().strip()
            
            # Cek Architecture
            stdin, stdout, stderr = ssh.exec_command("uname -m")
            arch = stdout.read().decode().strip()
            
            specs_text = f"""
💻 **Spesifikasi VPS:**
🎯 RAM: {ram_info}
💾 Disk: {disk_info}
🏗️ Arch: {arch}
"""
            progress_callback(specs_text)
            
            # Check if meets minimum requirements
            if "G" not in ram_info or int(ram_info.split("G")[0].split()[-1]) < 2:
                progress_callback("⚠️ Warning: Minimal 2GB RAM disarankan")
            
            return True
            
        except Exception as e:
            progress_callback(f"⚠️ Tidak bisa cek spesifikasi: {str(e)}")
            return True
    
    async def install_windows(self, host, username, password, windows_version, progress_callback):
        """Install Windows pada VPS"""
        ssh = None
        try:
            # Step 1: Koneksi SSH
            progress_callback("🔄 Menghubungkan ke VPS...")
            ssh = await self.connect_ssh(host, username, password)
            
            # Step 2: Cek spesifikasi
            await self.check_vps_specs(ssh, progress_callback)
            
            # Step 3: Upload script instalasi
            progress_callback("📤 Mengupload script instalasi...")
            
            # Pilih script berdasarkan config
            config = WINDOWS_CONFIG[windows_version]
            script_name = "netboot_install.sh"  # Default menggunakan netboot
            
            # Upload script yang dipilih
            sftp = ssh.open_sftp()
            with open(f"scripts/{script_name}", "r") as local_file:
                script_content = local_file.read()
            
            remote_script = "/tmp/install_windows.sh"
            with sftp.file(remote_script, "w") as remote_file:
                remote_file.write(script_content)
            
            sftp.chmod(remote_script, 0o755)
            sftp.close()
            
            # Step 4: Jalankan instalasi
            progress_callback("🚀 Memulai instalasi Windows...")
            progress_callback(f"📀 Versi: {config['name']}")
            progress_callback("⏰ Estimasi waktu: 20-60 menit")
            progress_callback("📡 Downloading ISO... (Tahap 1/3)")
            
            # Jalankan script dengan screen untuk persistensi
            command = f"bash {remote_script} {windows_version}"
            screen_cmd = f"screen -L -Logfile /tmp/win_install.log -dmS wininstall {command}"
            
            stdin, stdout, stderr = ssh.exec_command(screen_cmd)
            time.sleep(5)
            
            # Step 5: Monitor progress
            progress_checks = 0
            while progress_checks < 30:  # Max 30 checks (150 menit)
                await asyncio.sleep(30)  # Check setiap 30 detik
                
                # Cek jika screen masih berjalan
                stdin, stdout, stderr = ssh.exec_command("screen -list | grep wininstall")
                screen_status = stdout.read().decode()
                
                if "wininstall" not in screen_status:
                    progress_callback("🔍 Proses instalasi selesai, memeriksa hasil...")
                    break
                
                progress_checks += 1
                
                # Berikan progress update
                if progress_checks % 2 == 0:  # Setiap 1 menit
                    minutes = progress_checks // 2
                    progress_callback(f"⏳ Progress: {minutes} menit - Masih berjalan...")
                
                # Update tahapan setiap 10 menit
                if progress_checks == 4:  # 2 menit
                    progress_callback("🔧 Preparing installation... (Tahap 2/3)")
                elif progress_checks == 10:  # 5 menit
                    progress_callback("🏗️ Installing Windows... (Tahap 3/3)")
                elif progress_checks == 20:  # 10 menit
                    progress_callback("🎨 Finalizing setup...")
            
            # Step 6: Verifikasi instalasi
            progress_callback("✅ Proses instalasi selesai!")
            progress_callback("🔄 System akan reboot otomatis...")
            
            # Tunggu sebentar sebelum reboot
            await asyncio.sleep(10)
            
            # Reboot VPS
            ssh.exec_command("reboot")
            
            return True
            
        except Exception as e:
            raise Exception(f"❌ Error selama instalasi: {str(e)}")
        finally:
            if ssh:
                ssh.close()

# ===== INISIALISASI =====
installer = RDPInstaller()

# ===== HANDLER FUNCTIONS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler command /start"""
    keyboard = [
        [InlineKeyboardButton("🖥️ Install Windows", callback_data="install_menu")],
        [InlineKeyboardButton("📋 List Windows", callback_data="list_windows")],
        [InlineKeyboardButton("ℹ️ Cara Pakai", callback_data="help")],
        [InlineKeyboardButton("🔧 Check VPS", callback_data="check_vps")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """
🔥 BOT AUTO INSTALL RDP WINDOWS 🔥

Mau VPS Linux jadi Windows RDP? 
Gak perlu ribet, biar bot yang kerjain!

✅ Auto download & install
✅ Tidak perlu recovery mode  
✅ Full resource (bukan Docker)
✅ Proses cepat & otomatis
✅ Support Windows Server & Desktop

Pilih 🖥️ Install Windows untuk mulai!
    """
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def list_windows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan daftar Windows yang tersedia"""
    query = update.callback_query
    await query.answer()
    
    windows_list = "🖼️ **Pilihan Windows Tersedia:**\n\n"
    
    for key, config in WINDOWS_CONFIG.items():
        windows_list += f"• **{config['name']}**\n"
        windows_list += f"  💾 Size: {config['size']}\n"
        if 'notes' in config:
            windows_list += f"  📝 {config['notes']}\n"
        windows_list += f"  🏷️ Type: {'Server' if 'server' in key else 'Desktop'}\n\n"
    
    windows_list += "⚠️ **Persyaratan Minimal:**\n"
    windows_list += "• 2GB RAM\n• 25GB SSD\n• KVM/Virtualization\n• Koneksi internet stabil"
    
    await query.edit_message_text(windows_list)

async def install_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu pilihan Windows untuk install"""
    query = update.callback_query
    await query.answer()
    
    keyboard = []
    for key, config in WINDOWS_CONFIG.items():
        keyboard.append([InlineKeyboardButton(config['name'], callback_data=f"select_{key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="back_start")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Pilih versi Windows yang ingin diinstall:",
        reply_markup=reply_markup
    )

async def select_windows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pilih Windows version dan minta detail VPS"""
    query = update.callback_query
    await query.answer()
    
    windows_key = query.data.replace("select_", "")
    config = WINDOWS_CONFIG[windows_key]
    
    context.user_data['selected_windows'] = windows_key
    
    await query.edit_message_text(
        f"✅ Anda memilih: **{config['name']}**\n"
        f"💾 Size: {config['size']}\n\n"
        
        "Sekarang kirim detail VPS dalam format:\n"
        "`IP_USERNAME_PASSWORD`\n\n"
        "**Contoh:** `123.456.789.0_root_password123`\n\n"
        
        "⚠️ **PENTING:**\n"
        "• VPS harus dalam keadaan fresh/reset\n"
        "• Minimal 2GB RAM & 25GB SSD\n" 
        "• Support KVM/Virtualization\n"
        "• OS: Ubuntu/Debian/CentOS\n"
        "• Pastikan koneksi internet VPS stabil"
    )

async def handle_vps_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle input detail VPS"""
    if 'selected_windows' not in context.user_data:
        await update.message.reply_text("❌ Silakan pilih Windows terlebih dahulu!")
        return
    
    try:
        data = update.message.text.strip()
        parts = data.split('_')
        
        if len(parts) < 3:
            await update.message.reply_text("❌ Format salah! Gunakan: `IP_USERNAME_PASSWORD`")
            return
            
        ip = parts[0]
        username = parts[1]
        password = '_'.join(parts[2:])  # Handle password dengan underscore
        
        # Validasi IP sederhana
        if not ip.replace('.', '').isdigit():
            await update.message.reply_text("❌ Format IP tidak valid!")
            return
        
        # Simpan data VPS
        context.user_data['vps_ip'] = ip
        context.user_data['vps_username'] = username
        context.user_data['vps_password'] = password
        
        # Konfirmasi
        windows_key = context.user_data['selected_windows']
        config = WINDOWS_CONFIG[windows_key]
        
        keyboard = [
            [InlineKeyboardButton("✅ Ya, Install Sekarang", callback_data="confirm_install")],
            [InlineKeyboardButton("❌ Batal", callback_data="cancel_install")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📋 **Konfirmasi Instalasi**\n\n"
            f"🖥️ **Windows:** {config['name']}\n"
            f"💾 **Size:** {config['size']}\n"
            f"🌐 **IP VPS:** {ip}\n"
            f"👤 **Username:** {username}\n"
            f"🔑 **Password:** {'*' * len(password)}\n\n"
            f"⏰ **Estimasi waktu:** 20-60 menit\n"
            f"📊 **Data akan dihapus:** YA\n\n"
            f"Apakah Anda yakin ingin melanjutkan?",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}\n\nGunakan format: `IP_USERNAME_PASSWORD`")

async def confirm_install(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Konfirmasi dan mulai instalasi"""
    query = update.callback_query
    await query.answer()
    
    user_data = context.user_data
    chat_id = query.message.chat_id
    
    # Dapatkan data
    ip = user_data['vps_ip']
    username = user_data['vps_username']
    password = user_data['vps_password']
    windows_key = user_data['selected_windows']
    config = WINDOWS_CONFIG[windows_key]
    
    await query.edit_message_text(
        f"🚀 **Memulai Instalasi {config['name']}**\n\n"
        f"🌐 IP: {ip}\n"
        f"⏰ Estimasi: 20-60 menit\n\n"
        "Saya akan mengirim update progress di sini..."
    )
    
    # Fungsi callback untuk update progress
    async def progress_callback(message):
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send progress: {e}")
    
    try:
        # Jalankan instalasi
        success = await installer.install_windows(
            ip, username, password, windows_key, progress_callback
        )
        
        if success:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🎉 **INSTALASI BERHASIL!**\n\n"
                     f"Windows {config['name']} berhasil diinstall!\n\n"
                     "📝 **Default RDP Credentials:**\n"
                     "• Username: `Administrator`\n"
                     "• Password: `PasswordVPSAnda`\n\n"
                     "🔗 **Cara Akses RDP:**\n"
                     "1. Download Remote Desktop di PC\n"
                     "2. Ketik IP VPS: " + ip + "\n"
                     "3. Username: Administrator\n"
                     "4. Password: (password VPS Anda)\n\n"
                     "🔥 Selamat menikmati Windows RDP!"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Instalasi gagal. Silakan coba lagi atau hubungi admin."
            )
            
    except Exception as e:
        error_msg = f"❌ **ERROR SELAMA INSTALASI:**\n\n{str(e)}\n\n"
        error_msg += "**Solusi:**\n"
        error_msg += "• Pastikan VPS fresh/reset\n"
        error_msg += "• Cek koneksi internet VPS\n"
        error_msg += "• Pastikan spesifikasi cukup\n"
        error_msg += "• Coba dengan VPS provider berbeda"
        
        await context.bot.send_message(chat_id=chat_id, text=error_msg)

async def check_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cek koneksi dan spesifikasi VPS"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔧 **Check VPS**\n\n"
        "Kirim detail VPS untuk pengecekan:\n"
        "`IP_USERNAME_PASSWORD`\n\n"
        "Saya akan cek:\n"
        "• Koneksi SSH\n"
        "• Spesifikasi RAM & Disk\n"
        "• Kesesuaian untuk install Windows"
    )
    
    context.user_data['action'] = 'check_vps'

async def handle_vps_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pengecekan VPS"""
    if context.user_data.get('action') != 'check_vps':
        return
    
    try:
        data = update.message.text.strip()
        parts = data.split('_')
        
        if len(parts) < 3:
            await update.message.reply_text("❌ Format salah! Gunakan: `IP_USERNAME_PASSWORD`")
            return
            
        ip = parts[0]
        username = parts[1]
        password = '_'.join(parts[2:])
        
        await update.message.reply_text("🔍 Mengecek VPS...")
        
        # Koneksi dan cek spesifikasi
        ssh = await installer.connect_ssh(ip, username, password)
        
        # Cek RAM
        stdin, stdout, stderr = ssh.exec_command("free -h | grep Mem:")
        ram_info = stdout.read().decode().strip()
        
        # Cek Disk
        stdin, stdout, stderr = ssh.exec_command("df -h / | tail -1")
        disk_info = stdout.read().decode().strip()
        
        # Cek OS
        stdin, stdout, stderr = ssh.exec_command("cat /etc/os-release | grep PRETTY_NAME")
        os_info = stdout.read().decode().strip().replace('PRETTY_NAME=', '').replace('"', '')
        
        # Cek Virtualization
        stdin, stdout, stderr = ssh.exec_command("lscpu | grep Virtualization")
        virt_info = stdout.read().decode().strip()
        
        ssh.close()
        
        # Analisis hasil
        analysis = "✅ VPS SIAP untuk install Windows\n\n" if "G" in ram_info else "⚠️ VPS mungkin kurang optimal\n\n"
        
        check_result = f"""
📊 **HASIL CHECK VPS:**

💻 **OS:** {os_info}
🎯 **RAM:** {ram_info}
💾 **Disk:** {disk_info}
🔧 **Virtualization:** {virt_info if virt_info else 'Not detected'}

{analysis}
**Rekomendasi:**
• Minimal 2GB RAM
• Minimal 25GB SSD  
• Support KVM/Virtualization
• OS Ubuntu/Debian disarankan
        """
        
        await update.message.reply_text(check_result)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal mengecek VPS: {str(e)}")
    
    finally:
        context.user_data['action'] = None

async def cancel_install(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Batalkan instalasi"""
    query = update.callback_query
    await query.answer()
    
    # Hapus data user
    context.user_data.clear()
    
    await query.edit_message_text("❌ Instalasi dibatalkan.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command bantuan"""
    query = update.callback_query
    await query.answer()
    
    help_text = """
🆘 **BOT AUTO INSTALL RDP WINDOWS**

**CARA MENGGUNAKAN:**
1. **Siapkan VPS:**
   - Fresh/reset VPS
   - Minimal 2GB RAM
   - Minimal 25GB SSD
   - OS: Ubuntu/Debian/CentOS

2. **Install via Bot:**
   - Klik 🖥️ Install Windows
   - Pilih versi Windows
   - Kirim: `IP_USERNAME_PASSWORD`
   - Konfirmasi & tunggu

3. **Akses RDP:**
   - Gunakan IP VPS
   - User: Administrator  
   - Pass: (password VPS)

**⏰ ESTIMASI WAKTU:**
- Download: 5-30 menit
- Install: 10-30 menit  
- Total: 20-60 menit

**⚠️ PENTING:**
- Semua data existing akan dihapus
- Pastikan VPS support KVM
- Koneksi internet stabil

**❓ TROUBLESHOOTING:**
- Gagal koneksi: Cek IP/user/pass
- Gagal install: Cek spesifikasi VPS
- Timeout: Coba dengan VPS berbeda

**Support:** @username_anda
    """
    
    await query.edit_message_text(help_text)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle semua callback button"""
    query = update.callback_query
    data = query.data
    
    handlers = {
        "install_menu": install_menu,
        "list_windows": list_windows,
        "help": help_command,
        "check_vps": check_vps,
        "confirm_install": confirm_install,
        "cancel_install": cancel_install,
        "back_start": start
    }
    
    if data.startswith("select_"):
        await select_windows(update, context)
    elif data in handlers:
        await handlers[data](update, context)

# ===== MAIN FUNCTION =====
def main():
    """Main function"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vps_details))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vps_check))
    
    # Start bot
    print("🤖 Bot RDP Windows Installer started...")
    print("🔗 https://t.me/your_bot_username")
    application.run_polling()

if __name__ == "__main__":
    main()
