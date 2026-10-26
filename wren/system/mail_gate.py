# ============================================================
# WREN KERNEL — Mail Gate (Permission Layer)
# ------------------------------------------------------------
# PURPOSE: Binary authorization for mail access.
# STANDARD: Pure (Lean/Stable).
# ============================================================

from typing import Any

# The list of stewards authorized to access the mail system.
# Defaulting to 'wren' to ensure she can always read her own mail.
AUTHORIZED_STEWARDS = {"wren"}

def allowed_for(speaker: Any) -> bool:
    """
    Checks if the resolved speaker identity is authorized 
    to access mail context.
    """
    # Ensure speaker is a lowercase string for comparison
    speaker_id = str(speaker or "").strip().lower()
    return speaker_id in AUTHORIZED_STEWARDS
