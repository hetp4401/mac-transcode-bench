"""Fleet Browser on Apple Silicon: 4K HDR10 HEVC (like a Blu-ray remux) -> 1080p H.264 SDR, on the CPU (the fleet's
way) and with VideoToolbox (the Mac's media engine), timed."""
import os, re, subprocess, sys, time

FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
TONE = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
HDR = ["-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]


def run(args, timeout=900):
    t = time.time()
    r = subprocess.run(FF + args, capture_output=True, text=True, timeout=timeout)
    return time.time() - t, r.returncode, r.stderr.strip()[-400:]


def make_source():
    """12 s of 4K HDR10 HEVC 10-bit at ~60 Mbps, noisy so it's about as hard to decode as a remux."""
    pattern = ["-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=24000/1001,noise=alls=12:allf=t+u,format=p010le", "-t", "12"]
    for name, enc in (("hevc_videotoolbox", ["-c:v", "hevc_videotoolbox", "-profile:v", "main10", "-b:v", "60M", "-g", "24"]),
                      ("libx265", ["-c:v", "libx265", "-preset", "ultrafast", "-profile:v", "main10", "-x265-params", "keyint=24:bitrate=60000:log-level=error"])):
        dt, rc, err = run(pattern + enc + HDR + ["src.mkv"])
        if rc == 0 and os.path.getsize("src.mkv") > 1e6:
            print(f"made the test clip with {name} in {dt:.0f}s: {os.path.getsize('src.mkv') / 1e6:.0f} MB "
                  f"({os.path.getsize('src.mkv') * 8 / 12 / 1e6:.0f} Mbps)")
            return
        print(f"  {name} couldn't make it: {err}")
    sys.exit("no test clip")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                        "stream=codec_name,width,height,pix_fmt,color_transfer,nb_read_frames", "-of", "compact=p=0:nk=1", path],
                       capture_output=True, text=True)
    return r.stdout.strip()


def main():
    print(subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string", "hw.ncpu", "hw.memsize"], capture_output=True, text=True).stdout.replace("\n", " | "))
    make_source()
    print("source:", probe("src.mkv"))
    VT_IN = ["-hwaccel", "videotoolbox"]
    VT_IN_GPU = ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"]
    VT_OUT = ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-maxrate", "12M", "-profile:v", "high", "-allow_sw", "0"]
    X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high"]
    tests = [
        ("1. CPU, the fleet's way (software decode, x264)", 10, ["-ss", "1", "-i", "src.mkv", "-t", "10", "-vf", "scale=1920:-2," + TONE] + X264),
        ("2. VideoToolbox decode + encode, tone-mapping on the CPU", 10, VT_IN + ["-ss", "1", "-i", "src.mkv", "-t", "10", "-vf", "scale=1920:-2," + TONE] + VT_OUT),
        ("3. VideoToolbox decode + GPU scaling, tone-mapping on the CPU", 10, VT_IN_GPU + ["-ss", "1", "-i", "src.mkv", "-t", "10",
            "-vf", "scale_vt=w=1920:h=1080,hwdownload,format=p010le," + TONE] + VT_OUT),
        ("4. all hardware: VideoToolbox decode, GPU scaling + HDR->SDR, encode", 10, VT_IN_GPU + ["-ss", "1", "-i", "src.mkv", "-t", "10",
            "-vf", "scale_vt=w=1920:h=1080:color_matrix=bt709:color_primaries=bt709:color_transfer=bt709"] + VT_OUT),
        ("5. one 1-second piece (a seek), as in test 2", 1, VT_IN + ["-ss", "9", "-i", "src.mkv", "-t", "1", "-vf", "scale=1920:-2," + TONE] + VT_OUT),
        ("6. one 1-second piece (a seek), all hardware as in test 4", 1, VT_IN_GPU + ["-ss", "9", "-i", "src.mkv", "-t", "1",
            "-vf", "scale_vt=w=1920:h=1080:color_matrix=bt709:color_primaries=bt709:color_transfer=bt709"] + VT_OUT),
    ]
    for name, secs, args in tests:
        out = f"out{name[0]}.ts"
        dt, rc, err = run(args + ["-an", "-f", "mpegts", out])
        if rc:
            print(f"{name}: FAILED ({err})")
            continue
        info = probe(out)
        size = os.path.getsize(out)
        print(f"{name}: {secs}s of 4K HDR -> 1080p in {dt:.2f}s = {secs / dt:.1f}x real time "
              f"({size * 8 / secs / 1e6:.1f} Mbps out; {info})")


main()
