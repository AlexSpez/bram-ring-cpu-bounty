from pathlib import Path

root = Path(__file__).resolve().parent
for src, name in (("verify_avx2.c", "baseline"), ("verify_scalar_taps.c", "scalar")):
    code = (root / src).read_text()
    code = code.split("static void state_digest", 1)[0]
    code = code.replace("hash_state", f"{name}_hash_state")
    code = code.replace(f"static void {name}_hash_state", f"void {name}_hash_state")
    (root / f"bench_{name}.c").write_text(code)
