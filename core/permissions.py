def is_owner(member, cfg):
    if getattr(member, "id", None) in set(cfg["discord"].get("owner_ids", [])):
        return True
    guild = getattr(member, "guild", None)
    return bool(guild and getattr(guild, "owner_id", None) == getattr(member, "id", None))

def is_admin(member, cfg):
    if is_owner(member,cfg): return True
    allowed=set(cfg["discord"].get("admin_role_ids", []))
    return any(r.id in allowed for r in getattr(member,"roles",[]))

def is_staff(member, cfg):
    if is_admin(member,cfg): return True
    allowed=set(cfg["discord"].get("staff_role_ids", []))
    return any(r.id in allowed for r in getattr(member,"roles",[]))
