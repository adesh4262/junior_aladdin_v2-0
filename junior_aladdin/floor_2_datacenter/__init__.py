"""Junior Aladdin — Floor 2: Data Center (Data Truth Layer).

Floor 2 is the system's trusted data foundation. It preserves original truth,
validates quality, cleans artifacts, structures data into reusable streams,
tracks metadata and traceability, enables replay, and hands off structured
outputs to Floor 3.

Architecture rules:
- Floor 2 imports ONLY from shared/. No floor_3+ imports.
- Floor 2 generates truth, metadata, and validated structure ONLY — NOT intelligence.
- Floor 2 does NOT detect setups (FVG/OB/candidates belong to Floor 3).
- Quality facts are FACTUAL (packet_completeness=96%), NOT interpretive.
- Replay = first-class responsibility. Data Contract Registry = first-class governance.
"""
