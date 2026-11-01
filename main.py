import os
import platform
import re
import tarfile
import subprocess
import urllib.request
import zipfile
import sys
import tempfile
import shutil
from pathlib import Path

GPAC_VER = "v2.4.0"
PROJECT_DIR = Path(__file__).resolve().parent
BENTO4_DIR = PROJECT_DIR / "bento4"
WRAPPER_DIR = PROJECT_DIR / "wrapper"
AMD_DIR = PROJECT_DIR / "apple-music-downloader"
GO_ROOT = Path("/usr/local/go")
GO_MIN_VERSION = (1, 23, 1)

#Step: 1 Installation Segment
#Task: 1 Go Installation and also automatic update
def _parse_go_version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None

def _installed_go_version():
    go_bin = shutil.which("go") or str(GO_ROOT / "bin" / "go")
    try:
        out = subprocess.run([go_bin, "version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_go_version(out.replace("go version go", ""))

def _required_go_version():
    required = GO_MIN_VERSION
    gomod = PROJECT_DIR / "apple-music-downloader" / "go.mod"
    try:
        m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", gomod.read_text(), re.MULTILINE)
        if m:
            required = max(required, _parse_go_version(m.group(1)))
    except OSError:
        pass
    return required

def ensure_go():
    """Checking Go version and updateing if needed."""
    os.environ["PATH"] = f"{GO_ROOT / 'bin'}:{os.environ['PATH']}"

    required = _required_go_version()
    installed = _installed_go_version()
    req_str = ".".join(map(str, required))

    if installed and installed >= required:
        print(f"INFO: Go {'.'.join(map(str, installed))} OK (Required >= {req_str})")
        return True

    inst_str = ".".join(map(str, installed)) if installed else "brak"
    print(f"INFO: Go {inst_str} jest za stare (Required >= {req_str}), Updateing...")
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if not arch:
        print(f"WARN: Wrong platform: {platform.machine()}")
        return False

    tmp = Path("/tmp/go-update.tar.gz")
    try:
        with urllib.request.urlopen("https://go.dev/VERSION?m=text", timeout=30) as r:
            latest = r.read().decode().splitlines()[0].strip()
        url = f"https://go.dev/dl/{latest}.linux-{arch}.tar.gz"
        print(f"Download {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        shutil.rmtree(GO_ROOT, ignore_errors=True)
        with tarfile.open(tmp, "r:gz") as tar:
            tar.extractall("/usr/local")
        print(f"INFO: Updated {latest}")
        return True
    except Exception as e:
        print(f"WARN: Update didnt come throu: {e}")
        return False
    finally:
        if tmp.exists():
            tmp.unlink()

#Task: 2 Gpac installation cuz its not fckin workin
def install_gpac(apt, env):
    """Installing GPAC for MP4Box"""
    if shutil.which("MP4Box"):
        print("MP4Box is Installed <3")
        return
    has_pkg = subprocess.run(
        ["apt-cache", "show", "gpac"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0

    if has_pkg:
        r = subprocess.run([*apt, "install", "gpac"], env=env)
        if r.returncode == 0 and shutil.which("MP4Box"):
            print("GPAC Installed from APT.")
            return
                
    print(f"GPAC is unavailable from APT.\nInstalling from source\n{GPAC_VER}\n")
    subprocess.run(
        [*apt, "install", "build-essential", "pkg-config", "git", "zlib1g-dev"],
        check=True, env=env,
)

    build_dir = tempfile.mkdtemp(prefix="gpac-build-") 
    try:
        src = os.path.join(build_dir, "gpac")
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", GPAC_VER,
            "https://github.com/gpac/gpac.git", src],
            check=True, env=env,
        )
        subprocess.run(["./configure", "--static-bin"], cwd=src, check=True)
        subprocess.run(["make", f"-j{os.cpu_count() or 1}"], cwd=src, check=True)
        subprocess.run(["make", "install"], cwd=src, check=True)
    finally:
            shutil.rmtree(build_dir, ignore_errors=True)
    if not shutil.which("MP4Box"):
        raise RuntimeError("GPAC is built but MP4Box is not in the PATH.")
    print("GPAC is Ready")


def firstsetup():
    #Task: 3 Check for root
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root. Exiting...")
        sys.exit(1)

    try:
        
        #Task: 4 Install rest of packages
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        apt = ["apt-get", "-y", "-o", "Acquire::Retries=3", "-o", "Dpkg::Lock::Timeout=60"]

        subprocess.run([*apt, "update"], check=True, env=env)
        subprocess.run(
            [*apt, "install", "git", "ffmpeg", "wget",
             "python3-flask", "python3-yaml"],
            check=True,
            env=env,
        )

        if not ensure_go():
            raise RuntimeError("Couldn't install Go")
     
        install_gpac(apt, env)

        print("Packages installed successfully.")

                #Task: 5 Download and set up Bento4
        BENTO4_URL = "https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-unknown-linux.zip"
        zip_path = PROJECT_DIR / "bento4.zip"

        if not BENTO4_DIR.exists():
            try:
                print(f"Downloading Bento4 from {BENTO4_URL}...")
                req = urllib.request.Request(
                    BENTO4_URL,
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
                )
                with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
                    shutil.copyfileobj(resp, out)

                print("Extracting Bento4...")
                BENTO4_DIR.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(BENTO4_DIR)

                print("Bento4 installed inside project folder.")
            except Exception:
                shutil.rmtree(BENTO4_DIR, ignore_errors=True)
                raise
            finally:
                if zip_path.exists():
                    os.remove(zip_path)

            # Create symbolic links to Bento4 tools in /usr/local/bin
            bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
            if bin_candidates:
                bin_dir = bin_candidates[0] / "bin"
                print(f"DEBUG: Creating symbolic links for Bento4 tools from: {bin_dir}")
                print(f"DEBUG: Bin directory exists: {bin_dir.exists()}")
                
                if not bin_dir.exists():
                    print(f"ERROR: Bin directory does not exist: {bin_dir}")
                    return
                
                # List all files for debugging
                all_files = list(bin_dir.glob("*"))
                print(f"DEBUG: All files in bin: {[f.name for f in all_files]}")
                
                # First, make all files executable (ZIP extraction doesn't preserve execute permissions)
                print("Setting execute permissions on all Bento4 tools...")
                for exe_file in all_files:
                    if exe_file.is_file():
                        try:
                            # Add execute permission for owner, group, and others
                            current_mode = exe_file.stat().st_mode
                            new_mode = current_mode | 0o755  # rwxr-xr-x
                            exe_file.chmod(new_mode)
                            print(f"  CHMOD: Set execute permission on {exe_file.name}")
                        except Exception as e:
                            print(f"  ERROR: Failed to set execute permission on {exe_file.name}: {e}")
                
                # Now check for executable files again
                executable_files = [f for f in all_files if f.is_file() and os.access(f, os.X_OK)]
                print(f"DEBUG: Executable files after chmod: {[f.name for f in executable_files]}")
                
                # Add to current session PATH as well
                os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
                
                # Create symbolic links with detailed error reporting
                success_count = 0
                error_count = 0
                
                for exe_file in executable_files:
                    try:
                        link_path = Path("/usr/local/bin") / exe_file.name
                        print(f"DEBUG: Attempting to create symlink: {exe_file.name}")
                        print(f"DEBUG: Source: {exe_file.absolute()}")
                        print(f"DEBUG: Target: {link_path}")
                        
                        if link_path.exists():
                            print(f"  INFO: Already exists: {exe_file.name}")
                        else:
                            os.symlink(str(exe_file.absolute()), str(link_path))
                            print(f"  SUCCESS: Created symlink for {exe_file.name}")
                            success_count += 1
                            
                    except Exception as e:
                        print(f"  ERROR: Failed to create symlink for {exe_file.name}: {e}")
                        error_count += 1
                
                print(f"SUMMARY: {success_count} symlinks created, {error_count} errors")
                
                # Verify what actually got created
                print("Verifying /usr/local/bin contents...")
                usr_local_bin = Path("/usr/local/bin")
                if usr_local_bin.exists():
                    bento4_links = [f for f in usr_local_bin.glob("*") if f.is_symlink()]
                    print(f"Found {len(bento4_links)} symlinks in /usr/local/bin")
                    for link in bento4_links:
                        if any(exe.name == link.name for exe in executable_files):
                            print(f"  VERIFIED: {link.name} -> {link.readlink()}")
                else:
                    print("ERROR: /usr/local/bin does not exist")
            else:
                print("WARN: Could not find Bento4 extracted folder")
                
        else:
            print("INFO: Bento4 already exists, skipping download")
            
            # Ensure Bento4 tools are available even if already downloaded
            bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
            if bin_candidates:
                bin_dir = bin_candidates[0] / "bin"
                os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
                
                # Check if symbolic links need to be created
                try:
                    missing_links = []
                    for exe_file in bin_dir.glob("*"):
                        if exe_file.is_file() and os.access(exe_file, os.X_OK):
                            link_path = Path("/usr/local/bin") / exe_file.name
                            if not link_path.exists():
                                missing_links.append((exe_file, link_path))
                    
                    if missing_links:
                        print("Creating missing Bento4 symbolic links...")
                        for exe_file, link_path in missing_links:
                            os.symlink(exe_file, link_path)
                            print(f"  Created symlink: {exe_file.name}")
                    else:
                        print("✅ Bento4 tools already available system-wide")
                        
                except Exception as e:
                    print(f"WARN: Could not verify/create symbolic links: {e}")
                    print(f"Added existing Bento4 bin to current session PATH: {bin_dir}")

        # Step 3: Download and extract wrapper
        WRAPPER_URL = "https://github.com/WorldObservationLog/wrapper/releases/download/wrapper.x86_64.latest/Wrapper.x86_64.latest.zip"
        wrapper_zip = PROJECT_DIR / "wrapper.x86_64.zip"

        if not WRAPPER_DIR.exists():
            print(f"Downloading wrapper from {WRAPPER_URL}...")
            req = urllib.request.Request(WRAPPER_URL, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp, open(wrapper_zip, "wb") as out:
                    shutil.copyfileobj(resp, out)
                print("Extracting wrapper...")
                WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(wrapper_zip, "r") as zip_ref:
                    zip_ref.extractall(WRAPPER_DIR)
            except Exception:
                shutil.rmtree(WRAPPER_DIR, ignore_errors=True)
                raise
            finally:
                if wrapper_zip.exists():
                    os.remove(wrapper_zip)

            # Ensure the wrapper binary is executable (running as root, so no sudo needed)
            wrapper_bin = WRAPPER_DIR / "wrapper"
            try:
                if wrapper_bin.exists():
                    current_mode = wrapper_bin.stat().st_mode
                    wrapper_bin.chmod(current_mode | 0o755)
                    print("Set execute permission on wrapper binary")
                else:
                    print("WARN: Wrapper binary not found after extraction")
            except Exception as e:
                print(f"WARN: Failed to chmod wrapper binary: {e}")

            print("Wrapper extracted inside project folder")
        else:
            print("INFO: Wrapper already exists, skipping download")

        # Step 4: Clone Apple Music Downloader repo
        if not AMD_DIR.exists():
            print("Cloning Apple Music Downloader...")
            subprocess.run(
                ["git", "clone", "https://github.com/zhaarey/apple-music-downloader", str(AMD_DIR)],
                check=True
            )
            print("Apple Music Downloader cloned inside project folder")
        else:
            print("INFO: Apple Music Downloader already exists, skipping clone")

        print("First setup complete!")

    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed during setup: {e}")
        sys.exit(1)

def start():
    print("Starting Apple Music Downloader Web UI...")

    # Ensure Bento4 and Wrapper are in PATH locally
    bin_candidates = list(BENTO4_DIR.glob("Bento4*"))  # find extracted folder
    if bin_candidates:
        bin_dir = bin_candidates[0] / "bin"
        os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

    os.environ["PATH"] = f"{WRAPPER_DIR}:{os.environ['PATH']}"
    ensure_go()

    # Import and run the Flask app
    from app import app   # FIXED: no double "app.app"
    app.run(host="0.0.0.0", port=5000, debug=True)

# === First run check ===
marker_file = PROJECT_DIR / "firstrun"

if not marker_file.exists():
    firstsetup()
    with open(marker_file, "w") as f:
        f.write("This file marks that first setup has been completed.\n")

start()
