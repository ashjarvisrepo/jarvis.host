from core.permissions import is_owner,is_admin,is_staff

class Role:
    def __init__(self,id): self.id=id
class Member:
    def __init__(self,id,roles=()): self.id=id; self.roles=[Role(x) for x in roles]

CFG={"discord":{"owner_ids":[1],"admin_role_ids":[10],"staff_role_ids":[20]}}
def test_owner_has_all_privileges():
    m=Member(1)
    assert is_owner(m,CFG) and is_admin(m,CFG) and is_staff(m,CFG)
def test_admin_is_staff_but_not_owner():
    m=Member(2,[10])
    assert is_admin(m,CFG) and is_staff(m,CFG) and not is_owner(m,CFG)
def test_staff_not_admin():
    m=Member(3,[20])
    assert is_staff(m,CFG) and not is_admin(m,CFG)
def test_member_has_no_staff_access():
    m=Member(4)
    assert not is_staff(m,CFG)
