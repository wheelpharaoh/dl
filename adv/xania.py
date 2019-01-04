import adv_test
import adv
from wep.wand import flame as weapon
from core.timeline import *
from core.log import *



def module():
    return Xania

class Xania(adv.Adv):
    conf = {}
    conf.update( {
        "s1_dmg"      : 8.85 ,
        "s1_sp"       : 2759 ,
        "s1_startup"  : 0.1  ,
        "s1_recovery" : 1.35 ,

        "s2_dmg"      : 8.05 ,
        "s2_sp"       : 5570 ,
        "s2_startup"  : 0.1  ,
        "s2_recovery" : 1.35 ,

        "mod_a"   : ("s"    , 'passive' , 0.20) ,
        "mod_d"   : ('att'  , 'passive' , 0.60) ,
        "mod_wp"  : ('s'    , 'passive' , 0.25) ,
        "mod_wp2" : ('crit' , 'passive' , 0.06) ,

        } )
    conf.update(weapon.conf)


if __name__ == '__main__':
    conf = {}
    conf['acl'] = """
        `s1, seq=5 and cancel
        `s2, seq=5 and cancel
        `s3, seq=5 and cancel
        """
    adv_test.test(module(), conf, verbose=0)
