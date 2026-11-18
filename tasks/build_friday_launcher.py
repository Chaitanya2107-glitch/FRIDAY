"""Build the small Windows GUI launcher using the installed .NET compiler."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/launcher/FridayLauncher.cs'
OUTPUT = ROOT / 'dist/FRIDAY.exe'


def main():
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    assert compiler.is_file(), 'The Windows .NET Framework C# compiler is required.'
    OUTPUT.parent.mkdir(exist_ok=True)
    evidence = ROOT / 'tasks/friday-launcher'
    evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='friday-launcher-') as temporary:
        resource = Path(temporary) / 'root.txt'
        resource.write_text(str(ROOT), encoding='utf-8')
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/optimize+',
            '/reference:System.Windows.Forms.dll', f'/win32icon:{ROOT / "assets/friday.ico"}',
            f'/resource:{resource},FridayRoot', f'/out:{OUTPUT}', str(SOURCE)], check=True)
    binary = OUTPUT.read_bytes()
    pe = struct.unpack_from('<I', binary, 0x3c)[0]
    assert binary[:2] == b'MZ' and binary[pe:pe + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', binary, pe + 92)[0] == 2, 'Launcher must not open a console.'
    # Reflection exercises installation validation without starting or stopping FRIDAY.
    script = r'''
param([string]$Exe, [string]$Root)
$assembly = [Reflection.Assembly]::LoadFile($Exe)
$type = $assembly.GetType('FridayLauncher')
$flags = [Reflection.BindingFlags]'NonPublic,Static'
$found = $type.GetMethod('FindRoot', $flags).Invoke($null, @())
if ($found -ne $Root) { throw 'Launcher resolved the wrong project.' }
$validate = $type.GetMethod('IsInstallation', $flags)
if (-not $validate.Invoke($null, @($Root))) { throw 'Installation validation failed.' }
if ($validate.Invoke($null, @([IO.Path]::GetTempPath()))) { throw 'Invalid installation accepted.' }
'''
    probe = evidence / 'check.ps1'
    probe.write_text(script, encoding='utf-8')
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(probe), str(OUTPUT), str(ROOT)], check=True)
    receipt = {'passed': True, 'authorization': 'Owner requested an EXE to start FRIDAY',
               'executable': str(OUTPUT), 'bytes': len(binary), 'console_window': False,
               'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               'binary_sha256': hashlib.sha256(binary).hexdigest(),
               'checks': ['GUI PE subsystem', 'resolves installed project', 'rejects missing installation'],
               'limit': 'Launcher uses the existing project, Python environment and Island build.'}
    (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
