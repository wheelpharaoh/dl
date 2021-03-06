import adv.adv_test
from core.advbase import *
from module.bleed import Bleed
from slot.a import *

def module():
    return Addis


class Addis(Adv):
    comment = 's2 c2 s1 c5fsf c4fs s1; hold s2s1 until bleed under 3'

    a3 = ('bk',0.20)
    conf = {}
    conf['acl'] = """
        `s2, s1.charged>=s1.sp-260 and seq=5 and this.bleed._static['stacks'] != 3
        `s1, s2.charged<s2.sp and this.bleed._static['stacks'] != 3
        `s3, seq=5 and not this.s2buff.get()
        `fs, this.s2buff.get() and seq=4 and this.s1.charged>=s1.sp-200
        """
    conf['afflict_res.poison'] = 0

    def getbleedpunisher(this):
        if this.bleed._static['stacks'] > 0:
            return 0.08
        return 0

    def prerun(this):
        random.seed()
        this.s2buff = Selfbuff("s2_shapshifts1",1, 10,'ss','ss')
        this.s2str = Selfbuff("s2_str",0.25,10)
        this.bleedpunisher = Modifier("bleed","att","killer",0.08)
        this.bleedpunisher.get = this.getbleedpunisher
        this.bleed = Bleed("g_bleed",0).reset()
        #this.crit_mod = this.rand_crit_mod


    def s1_proc(this, e):

        if this.s2buff.get():
            this.s2buff.buff_end_timer.timing += 2.5
            this.s2str.buff_end_timer.timing += 2.5
            log('-special','s1_with_s2')
            if random.random() < 0.8:
                Bleed("s1", 1.32).on()
            else:
                log('-special','s1_failed')
        else:
            this.afflics.poison('s1',100,0.53)


    def s2_proc(this, e):
        this.s2buff.on()
        this.s2str.on()


if __name__ == '__main__':
    conf = {}
    adv.adv_test.test(module(), conf)

