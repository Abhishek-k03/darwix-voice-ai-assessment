"""PT Maju Bersama Finance (fictional) — Indonesia multifinance (motorbike financing) corpus for Q3.

Website FAQ in formal Bahasa Indonesia; call playbook mixes formal guidance with colloquial customer phrases.
"""

from __future__ import annotations

from pathlib import Path

from . import render

BRAND = {
    "name": "Maju Bersama Finance",
    "tagline": "Pembiayaan motor mudah dan aman",
    "home": "/id_multifinance/site/index.html",
    "helpline": "Halo Maju 1500-123 | Senin-Sabtu 08.00-20.00 WIB",
    "cookie": "Situs ini menggunakan cookie untuk meningkatkan pengalaman Anda.",
    "footer": "© 2025 PT Maju Bersama Finance (fiktif). Terdaftar dan diawasi oleh Otoritas Jasa Keuangan (OJK).",
    "nav": [
        ("Beranda", "/id_multifinance/site/index.html"),
        ("Pembiayaan Motor", "/id_multifinance/site/pembiayaan-motor.html"),
        ("Pembayaran Angsuran", "/id_multifinance/site/pembayaran.html"),
        ("Hubungi Kami", "/id_multifinance/site/kontak.html"),
    ],
}

PAGES = {
    "index.html": ("Pembiayaan motor baru dan bekas", """
<p>PT Maju Bersama Finance menyediakan pembiayaan sepeda motor baru dan bekas dengan proses cepat, DP ringan, dan tenor fleksibel.</p>
<p>Kantor cabang tersedia di Jawa, Sumatra, dan Sulawesi. Semua transaksi resmi hanya melalui kanal pembayaran resmi perusahaan.</p>
"""),
    "pembiayaan-motor.html": ("Pembiayaan Motor", """
<h2>Ketentuan pembiayaan</h2>
<ul>
<li>Uang muka (DP) mulai dari 15% dari harga on the road.</li>
<li>Pilihan tenor 12, 18, 24, 30, atau 36 bulan.</li>
<li>Angsuran tetap setiap bulan selama tenor, dibayar setiap tanggal jatuh tempo yang tercantum di kontrak.</li>
<li>Asuransi kendaraan (total loss only) sudah termasuk selama masa pembiayaan.</li>
</ul>
<h2>Pelunasan dipercepat</h2>
<p>Konsumen dapat melunasi pembiayaan lebih cepat dengan biaya penalti 3% dari sisa pokok utang. BPKB dapat diambil di kantor cabang paling lambat 14 hari kerja setelah lunas.</p>
"""),
    "pembayaran.html": ("Pembayaran angsuran dan denda", """
<h3>Kapan tanggal jatuh tempo angsuran saya?</h3>
<p>Tanggal jatuh tempo sama setiap bulan sesuai kontrak pembiayaan. Kami mengirim pengingat melalui SMS dan WhatsApp 3 hari sebelum jatuh tempo.</p>
<h3>Berapa denda keterlambatan?</h3>
<p>Denda keterlambatan sebesar 0,2% per hari dari angsuran yang tertunggak, dihitung sejak hari pertama setelah tanggal jatuh tempo. Tidak ada masa tenggang.</p>
<h3>Di mana saya bisa membayar cicilan?</h3>
<p>Melalui virtual account BCA, BRI, Mandiri, dan BNI; gerai Indomaret, Alfamart, dan Kantor Pos; aplikasi MajuKu; serta dompet digital GoPay, OVO, DANA, dan ShopeePay.
Pembayaran terkonfirmasi otomatis paling lambat 1x24 jam.</p>
<h3>Bolehkah saya mengubah tanggal jatuh tempo?</h3>
<p>Boleh, satu kali selama masa kontrak, dengan biaya administrasi Rp50.000. Ajukan melalui aplikasi MajuKu atau Halo Maju 1500-123.</p>
<h3>Bagaimana jika saya sudah membayar tetapi masih ditagih?</h3>
<p>Simpan bukti pembayaran dan hubungi Halo Maju 1500-123. Kami akan melakukan pengecekan dan rekonsiliasi paling lambat 1x24 jam.</p>
<h3>Apakah saya boleh membayar melalui petugas atau rekening pribadi?</h3>
<p>Tidak. Jangan pernah membayar ke rekening pribadi atau menitipkan uang kepada siapa pun. Gunakan hanya kanal pembayaran resmi.</p>
"""),
    "kontak.html": ("Hubungi Kami", """
<p>Halo Maju 1500-123, Senin sampai Sabtu pukul 08.00-20.00 WIB. E-mail: halo@majubersama.example.</p>
<p>Pengaduan juga dapat disampaikan melalui Kontak OJK 157.</p>
"""),
}

ETIKA = """# Ringkasan Etika Penagihan (internal)

Disusun dari ketentuan perlindungan konsumen OJK (POJK 22/2023). Ringkasan internal — rujuk peraturan untuk teks resmi.

## Waktu penagihan
Penagihan dan pengingat hanya dilakukan hari Senin sampai Sabtu, di luar hari libur nasional, pukul 08.00 sampai 20.00 waktu setempat.

## Larangan
Petugas dilarang menggunakan ancaman, kekerasan, atau tindakan yang mempermalukan konsumen; dilarang menekan secara fisik maupun verbal;
dilarang menagih kepada pihak selain konsumen; dan dilarang menghubungi secara terus-menerus sehingga mengganggu.

## Identitas
Petugas wajib menyebutkan nama dan nama perusahaan di awal percakapan, serta menjelaskan tujuan panggilan.
"""

OBJECTIONS = """# Playbook Panggilan Pengingat Angsuran — Maju Bersama Finance (internal)

Versi 2.0 — disetujui Compliance 2025-01-15. Selalu sapa dengan "Bapak" atau "Ibu". Ikuti gaya bahasa konsumen (formal atau santai)
tetapi tetap sopan. Tidak boleh mengancam.

## Keberatan: "Belum gajian, Mbak/Mas"
Tanyakan tanggal gajian. Jelaskan bahwa denda 0,2% per hari dihitung sejak hari setelah jatuh tempo, jadi membayar sedekat mungkin dengan
jatuh tempo akan mengurangi denda. Tawarkan pengingat ulang di tanggal gajian.

## Keberatan: "Lagi susah, usaha lagi sepi" / "Saya baru kena PHK"
Tunjukkan empati. Sampaikan bahwa ada program restrukturisasi untuk konsumen yang penghasilannya menurun, dan tawarkan agar tim restrukturisasi
menghubungi kembali. Jangan menjanjikan persetujuan.

## Keberatan: "Nanti aja deh, kok ditelpon terus sih?"
Minta maaf atas ketidaknyamanannya, konfirmasi waktu yang paling nyaman untuk dihubungi, dan sampaikan tanggal jatuh tempo dengan singkat.

## Keberatan: "Saya udah bayar kok"
Ucapkan terima kasih, minta konsumen menyimpan bukti bayar, dan jelaskan bahwa pembayaran terkonfirmasi paling lambat 1x24 jam.
Jika sudah lebih dari 1x24 jam, tawarkan pengecekan oleh Halo Maju 1500-123.

## Keberatan: "Ini penipuan ya?"
Sampaikan nama perusahaan, sarankan verifikasi ke Halo Maju 1500-123, dan tegaskan bahwa kami tidak pernah meminta pembayaran ke rekening pribadi atau meminta kode OTP.
"""


def build(root: Path) -> None:
    for rel, (title, body) in PAGES.items():
        render.write(root / "site" / rel, render.html_page(brand=BRAND, title=title, body=body, lang="id"))
    render.pdf_document(root / "docs" / "kebijakan_restrukturisasi_2025.pdf",
                        header="PT Maju Bersama Finance | Kebijakan Restrukturisasi", footer="Dokumen KR-2025-01",
                        title="Program Restrukturisasi Pembiayaan (berlaku 1 Januari 2025)", sections=[
        ("Kriteria konsumen", [
            "Restrukturisasi dapat diajukan oleh konsumen yang mengalami penurunan penghasilan karena PHK atau usaha menurun, "
            "sakit berat atau rawat inap, atau terdampak bencana alam.",
        ]),
        ("Pilihan keringanan", [
            "Perpanjangan tenor paling lama 12 bulan; penundaan pembayaran pokok paling lama 3 bulan; dan keringanan denda keterlambatan.",
        ]),
        ("Persyaratan dokumen", [
            "KTP, surat keterangan (PHK, dokter, atau RT/RW), dan mutasi rekening atau bukti penghasilan 3 bulan terakhir.",
        ]),
        ("Proses", [
            "Pengajuan melalui Halo Maju 1500-123 atau aplikasi MajuKu. Analis restrukturisasi menghubungi konsumen dalam 3 hari kerja, "
            "dan keputusan diberikan paling lambat 14 hari kerja. Program ini tidak dipungut biaya apa pun.",
        ]),
    ])
    render.write(root / "internal" / "etika_penagihan.md", ETIKA)
    render.write(root / "internal" / "objection_playbook_id.md", OBJECTIONS)
