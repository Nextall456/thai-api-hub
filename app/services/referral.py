"""Referral system: ลิงก์แนะนำ + รางวัล 30 วันเมื่อคนที่แนะนำจ่ายเงิน"""
from datetime import datetime, timedelta

from .. import config, db


REFERRAL_REWARD_DAYS = 30


def grant_referral_reward(referred_user_id: int) -> int | None:
    """เมื่อผู้ถูกแนะนำจ่ายเงินสำเร็จ → ผู้แนะนำได้ฟรี 30 วัน (ต่อจาก sub หรือ trial)
    คืน user_id ของผู้แนะนำ ถ้าให้รางวัลสำเร็จ, None ถ้าไม่มี/ให้ไปแล้ว"""
    ref = db.q("SELECT referred_by FROM users WHERE id=?", (referred_user_id,), one=True)
    if not ref or not ref["referred_by"]:
        return None
    referrer_id = ref["referred_by"]

    # กันรางวัลซ้ำ: ผู้แนะนำคนเดียวกัน ให้ครั้งเดียวต่อ 1 ผู้ถูกแนะนำ
    already = db.q("SELECT id FROM audit_logs WHERE action='referral_reward' AND user_id=? AND detail LIKE ?",
                   (referrer_id, f"%ref={referred_user_id}#%"), one=True)
    if already:
        return None

    referrer = db.q("SELECT * FROM users WHERE id=?", (referrer_id,), one=True)
    if not referrer:
        return None

    sub = db.q("SELECT * FROM subscriptions WHERE user_id=? AND status='active' AND ends_at>? "
               "ORDER BY ends_at DESC LIMIT 1", (referrer_id, db.now_str()), one=True)
    if sub:  # ต่อจากวันหมดอายุเดิม
        base = datetime.strptime(sub["ends_at"], db.FMT)
        new_end = (base + timedelta(days=REFERRAL_REWARD_DAYS)).strftime(db.FMT)
        db.x("UPDATE subscriptions SET ends_at=? WHERE id=?", (new_end, sub["id"]))
        reward_to = f"ต่ออายุ sub #{sub['id']} ถึง {new_end}"
    else:  # ไม่มี sub → ยืด trial ออกไป
        base = referrer.get("trial_ends_at") or db.now_str()
        try:
            b = datetime.strptime(base, db.FMT)
        except ValueError:
            b = datetime.now()
        if b < datetime.now():
            b = datetime.now()
        new_trial = (b + timedelta(days=REFERRAL_REWARD_DAYS)).strftime(db.FMT)
        db.x("UPDATE users SET trial_ends_at=? WHERE id=?", (new_trial, referrer_id))
        reward_to = f"ยืด trial ถึง {new_trial}"

    from .security import audit
    audit(referrer_id, "referral_reward",
          f"ref={referred_user_id}# รางวัลแนะนำเพื่อน +{REFERRAL_REWARD_DAYS} วัน → {reward_to}")
    return referrer_id


def referral_stats(user_id: int) -> dict:
    me = db.q("SELECT referral_code FROM users WHERE id=?", (user_id,), one=True)
    code = (me or {}).get("referral_code") or ""
    referred = db.q(
        "SELECT u.email, u.name, u.created_at FROM users u WHERE u.referred_by=? ORDER BY u.id DESC",
        (user_id,))
    rewards = db.q("SELECT COUNT(*) c FROM audit_logs WHERE action='referral_reward' AND user_id=?",
                   (user_id,), one=True)["c"]
    return {
        "code": code,
        "link": f"{config.SITE_URL}/signup?ref={code}",
        "referred_count": len(referred),
        "referred": referred,
        "rewards_granted": rewards,
        "reward_days": REFERRAL_REWARD_DAYS,
    }
