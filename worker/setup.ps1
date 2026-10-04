# Mobiloda 3D işleyici kurulumu (Windows, NVIDIA ekran kartı)
# Çalıştırma:  powershell -ExecutionPolicy Bypass -File worker\setup.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$TRIPOSR_COMMIT = '107cefdc244c39106fa830359024f6a2f1c78871'

if (-not (Test-Path .venv)) {
    Write-Host '> Sanal ortam (venv) oluşturuluyor...'
    python -m venv .venv
}
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path triposr)) {
    Write-Host '> TripoSR indiriliyor...'
    git clone https://github.com/VAST-AI-Research/TripoSR.git triposr
    git -C triposr checkout $TRIPOSR_COMMIT
    # Windows uyumluluğu: torchmcubes yerine PyMCubes, doku pişirmede GPU düzeltmesi
    git -C triposr apply ..\triposr.patch
}

Write-Host '> Paketler kuruluyor (PyTorch ~2.5 GB, biraz sürebilir)...'
& $py -m pip install --upgrade pip
& $py -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
& $py -m pip install -r requirements.txt

& $py -c "import torch; print('CUDA:', torch.cuda.is_available())"
Write-Host '> Kurulum tamam. TripoSR modeli (~1.7 GB) ilk çalıştırmada otomatik iner.'
