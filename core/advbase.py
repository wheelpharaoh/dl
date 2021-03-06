import operator
import sys
import random
from functools import reduce
from itertools import product

from ability import Ability, Overdrive_Punisher
from core import *
from core.timeline import *
from core.log import *
from core.afflic import *
import core.acl
import conf as globalconf
import slot
import core.floatsingle as floatsingle

# import core.condition
# m_condition = core.condition
from core.condition import Condition

conf = Conf()


class ModifierDict(defaultdict):
    def __init__(this, *args, **kwargs):
        if args:
            super().__init__(*args, **kwargs)
        else:
            super().__init__(lambda: defaultdict(lambda: []))

    def append(this, modifier):
        this[modifier.mod_type][modifier.mod_order].append(modifier)

    def remove(this, modifier):
        this[modifier.mod_type][modifier.mod_order].remove(modifier)


class Modifier(object):
    _static = Static({
        'all_modifiers': ModifierDict(),
        'g_condition': None
    })
    mod_name = '<nop>'
    mod_type = '_nop' or 'att' or 'x' or 'fs' or 's'  # ....
    mod_order = '_nop' or 'passive' or 'ex' or 'buff'  # chance dmg for crit
    mod_value = 0

    def __init__(this, name, mtype, order, value, condition=None, get=None):
        this.mod_name = name
        this.mod_type = mtype
        this.mod_order = order
        this.mod_value = value
        this.mod_condition = condition
        this.mod_get = get
        this._mod_active = 0
        this.on()
        # this._static.all_modifiers.append(this)
        # this.__active = 1

    @classmethod
    def mod(cls, mtype, all_modifiers=None):
        if not all_modifiers:
            all_modifiers = cls._static.all_modifiers
        m = defaultdict(lambda: 1)
        for order, modifiers in all_modifiers[mtype].items():
            m[order] += sum([modifier.get() for modifier in modifiers])
        ret = 1.0
        for i in m:
            ret *= m[i]
        return ret

    def get(this):
        if callable(this.mod_get) and not this.mod_get():
            return 0
        return this.mod_value

    def on(this, modifier=None):
        if this._mod_active == 1:
            return this
        if modifier == None:
            modifier = this
        # if modifier.mod_condition:
        #     if not m_condition.on(modifier.mod_condition):
        #         return this
        if modifier.mod_condition is not None:
            if not this._static.g_condition(modifier.mod_condition):
                return this

        this._static.all_modifiers.append(this)
        this._mod_active = 1
        return this

    def off(this, modifier=None):
        if this._mod_active == 0:
            return this
        this._mod_active = 0
        if modifier == None:
            modifier = this
        this._static.all_modifiers.remove(this)
        return this

    def __enter__(this):
        this.on()

    def __exit__(this, exc_type, exc_val, exc_tb):
        this.off()

    def __repr__(this):
        return '<%s %s %s %s>' % (this.mod_name, this.mod_type, this.mod_order, this.mod_value)


class KillerModifier(Modifier):
    def __init__(this, name, order, value, killer_condition):
        this.killer_condition = killer_condition
        super().__init__(name, f"{killer_condition}_killer", order, value)

    def on(this, modifier=None):
        if this._mod_active == 1:
            return this
        if modifier == None:
            modifier = this
        if modifier.mod_condition is not None:
            if not this._static.g_condition(modifier.mod_condition):
                return this

        for kcondition in this.killer_condition:
            this._static.all_modifiers[f"{kcondition}_killer"][this.mod_order].append(modifier)
        this._mod_active = 1
        return this

    def off(this, modifier=None):
        if this._mod_active == 0:
            return this
        this._mod_active = 0
        if modifier == None:
            modifier = this
        for kcondition in this.killer_condition:
            this._static.all_modifiers[f"{kcondition}_killer"][this.mod_order].remove(this)
        return this


class CrisisModifier(Modifier):
    def __init__(this, name, scale, hp):
        super().__init__('mod_{}_crisis'.format(name), 'att', 'hit', 0)
        this.hp_scale = scale
        this.hp_lost = 100 - hp
        if hp == 0:
            this.hp_cond = this._static.g_condition('hp=1')
        elif hp < 100:
            this.hp_cond = this._static.g_condition('hp={}%'.format(hp))
        else:
            this.hp_cond = 0

    def get(this):
        if this.hp_cond:
            this.mod_value = this.hp_scale * (this.hp_lost ** 2) / 10000
        else:
            this.mod_value = 0
        return this.mod_value


class Buff(object):
    _static = Static({
        'all_buffs': [],
        'time_func': 0,
    })

    def __init__(this, name='<buff_noname>', value=0, duration=0, mtype=None, morder=None):
        this.name = name
        this.__value = value
        this.duration = duration
        this.mod_type = mtype or 'att' or 'x' or 'fs' or 's'  # ....
        this.bufftype = ''
        if morder == None:
            if this.mod_type == 'crit':
                this.mod_order = 'chance'
            else:
                this.mod_order = 'buff'
        else:
            this.mod_order = morder or '<null>' or 'passive' or 'ex' or 'buff' or 'punisher'  # ...

        if this.mod_order != 'buff':
            this.bufftime = this.nobufftime
        if not this._static.time_func:
            this._static.time_func = this.nobufftime

        this.buff_end_timer = Timer(this.buff_end_proc)
        this.modifier = Modifier('mod_' + this.name, this.mod_type, this.mod_order, 0)
        this.modifier.get = this.get
        this.dmg_test_event = Event('dmg_formula')
        this.dmg_test_event.dmg_coef = 1
        this.dmg_test_event.dname = 'test'

        this.__stored = 0
        this.__active = 0
        # this.on()

    def nobufftime(this):
        return 1

    def bufftime(this):
        return this._static.time_func()

    def value(this, newvalue=None):
        if newvalue:
            return this.set(newvalue)
        else:
            return this.get()

    def get(this):
        if this.__active:
            return this.__value
        else:
            return 0

    def set(this, v, d=None):
        this.__value = v
        if d != None:
            this.duration = d
        return this

    def stack(this):
        stack = 0
        for i in this._static.all_buffs:
            if i.name == this.name:
                if i.__active != 0:
                    stack += 1
        return stack

    def valuestack(this):
        stack = 0
        value = 0
        for i in this._static.all_buffs:
            if i.name == this.name:
                if i.__active != 0:
                    stack += 1
                    value += i.__value
        return value, stack

    def buff_end_proc(this, e):
        log('buff', this.name, '%s: %.2f' % (this.mod_type, this.value()), this.name + ' buff end <timeout>')
        this.__active = 0

        if this.__stored:
            idx = len(this._static.all_buffs)
            while 1:
                idx -= 1
                if idx < 0:
                    break
                if this == this._static.all_buffs[idx]:
                    this._static.all_buffs.pop(idx)
                    break
            this.__stored = 0
        value, stack = this.valuestack()
        if stack > 0:
            log('buff', this.name, '%s: %.2f' % (this.mod_type, value), this.name + ' buff stack <%d>' % stack)
        this.modifier.off()

    def on(this, duration=None):
        if duration == None:
            d = this.duration * this.bufftime()
        else:
            d = duration * this.bufftime()
        if this.__active == 0:
            this.__active = 1
            if this.__stored == 0:
                this._static.all_buffs.append(this)
                this.__stored = 1
            if d >= 0:
                this.buff_end_timer.on(d)
            log('buff', this.name, '%s: %.2f' % (this.mod_type, this.value()), this.name + ' buff start <%ds>' % d)
        else:
            if d >= 0:
                this.buff_end_timer.on(d)
                log('buff', this.name, '%s: %.2f' % (this.mod_type, this.value()),
                    this.name + ' buff refresh <%ds>' % d)

        value, stack = this.valuestack()
        if stack > 1:
            log('buff', this.name, '%s: %.2f' % (this.mod_type, value), this.name + ' buff stack <%d>' % stack)

        if this.mod_type == 'defense':
            Event('defchain').on()

        this.modifier.on()
        return this

    def off(this):
        if this.__active == 0:
            return
        log('buff', this.name, '%s: %.2f' % (this.mod_type, this.value()), this.name + ' buff end <turn off>')
        this.__active = 0
        this.modifier.off()
        this.buff_end_timer.off()
        return this

    def __bool__(this):
        return bool(this.get())


class Selfbuff(Buff):
    def __init__(this, name='<buff_noname>', value=0, duration=0, mtype=None, morder=None):
        Buff.__init__(this, name, value, duration, mtype, morder)
        this.bufftype = 'self'
        this.bufftime = this._bufftime

    def _bufftime(this):
        return this._static.time_func()

    def buffcount(this):
        bc = 0
        for i in this._static.all_buffs:
            if i.get() and i.bufftype == 'self' or i.bufftype == 'team':
                bc += 1
        return bc


class SingleActionBuff(Buff):
    # this buff lasts until the action it is buffing is completed
    def __init__(this, name='<buff_noname>', value=0, casts=1, mtype=None, morder=None, event=None):
        super().__init__(name, value, -1, mtype, morder)
        this.bufftype = 'self'
        this.casts = casts
        this.end_event = event if event is not None else mtype
        if isinstance(this.end_event, str):
            Listener(this.end_event, this.l_off).on()
        else:
            for e in this.end_event:
                Listener(e, this.l_off).on()

    def on(this, casts=1):
        this.casts = casts
        return super().on(-1)

    def l_off(this, e):
        this.casts -= 1
        if this.casts <= 0:
            return super().off()
        else:
            return this


class Teambuff(Buff):
    def __init__(this, name='<buff_noname>', value=0, duration=0, mtype=None, morder=None):
        Buff.__init__(this, name, value, duration, mtype, morder)
        this.bufftype = 'team'
        this.bufftime = this._bufftime

    def _bufftime(this):
        return this._static.time_func()

    def on(this, duration=None):
        Buff.on(this, duration)
        this.count_team_buff()
        return this

    def off(this):
        Buff.off(this)
        this.count_team_buff()
        return this

    def buff_end_proc(this, e):
        Buff.buff_end_proc(this, e)
        this.count_team_buff()

    def count_team_buff(this):
        this.dmg_test_event.modifiers = ModifierDict()
        for i in this._static.all_buffs:
            if i.name == 'simulated_def':
                this.dmg_test_event.modifiers.append(i.modifier)
        this.dmg_test_event()
        no_team_buff_dmg = this.dmg_test_event.dmg
        sd_mods = 1
        for i in this._static.all_buffs:
            if i.bufftype == 'team' or i.bufftype == 'debuff':
                if i.modifier.mod_type == 's':
                    sd_mods = 1 + i.get() * 1 / 2
                else:
                    this.dmg_test_event.modifiers.append(i.modifier)
        this.dmg_test_event()
        team_buff_dmg = this.dmg_test_event.dmg * sd_mods
        log('buff', 'team', team_buff_dmg / no_team_buff_dmg - 1)


class Spdbuff(Buff):
    def __init__(this, name='<buff_noname>', value=0, duration=0, mtype=None, morder=None, wide='self'):
        mtype = 'spd'
        morder = 'passive'
        Buff.__init__(this, name, value, duration, mtype, morder)
        this.bufftype = wide
        this.bufftime = this._bufftime
        Event('speed')()

    def _bufftime(this):
        return this._static.time_func()

    def on(this, duration=None):
        Buff.on(this, duration)
        this.count_team_buff()
        return this

    def off(this):
        Buff.off(this)
        this.count_team_buff()
        return this

    def buff_end_proc(this, e):
        Buff.buff_end_proc(this, e)
        this.count_team_buff()

    def count_team_buff(this):
        this.dmg_test_event.modifiers = ModifierDict()
        for i in this._static.all_buffs:
            if i.name == 'simulated_def':
                this.dmg_test_event.modifiers.append(i.modifier)
        this.dmg_test_event()
        no_team_buff_dmg = this.dmg_test_event.dmg
        sd_mods = 1
        for i in this._static.all_buffs:
            if i.bufftype == 'team' or i.bufftype == 'debuff':
                if i.modifier.mod_type == 's':
                    sd_mods = 1 + i.get() * 1 / 2
                else:
                    this.dmg_test_event.modifiers.append(i.modifier)
        this.dmg_test_event()
        team_buff_dmg = this.dmg_test_event.dmg * sd_mods
        spd = this.stack() * this.value()
        if this.bufftype == 'team' or this.bufftype == 'debuff':
            team_buff_dmg += team_buff_dmg * spd
        log('buff', 'team', team_buff_dmg / no_team_buff_dmg - 1)


class Debuff(Teambuff):
    def __init__(this, name='<buff_noname>', value=0, duration=0, chance='1', mtype='def', morder=None):
        value = 0 - value
        chance = float(chance)
        if chance != 1:
            bd = 1.0 / (1.0 + value)
            bd = (bd - 1) * chance + 1
            value = 1 - 1.0 / bd
            value = 0 - value
        Teambuff.__init__(this, name, value, duration, mtype, morder)
        this.bufftype = 'debuff'
        this.bufftime = this.nobufftime

    def chance(c):
        bd = 1.0 / (1.0 + this.value)
        bd = (bd - 1) * c + 1
        this.value = 1 - 1.0 / bd
        return this


class Skill(object):
    _static = Static({
        's_prev': '<nop>',
        'first_x_after_s': 0,
        'silence': 0,
    })
    charged = 0
    sp = 0
    silence_duration = 1.9
    name = '_Skill'

    def __init__(this, name=None, conf=None, ac=None):
        this.charged = 0
        if name:
            this.name = name
        if conf:
            this.conf = conf
            conf.sync_skill = this.sync_sp
        if ac:
            this.ac = ac
        elif conf:
            this.ac = S(this.name, this.conf)

        this._static.silence = 0
        this.silence_end_timer = Timer(this.cb_silence_end)
        this.silence_end_event = Event('silence_end')
        this.skill_charged = Event('{}_charged'.format(this.name))
        this.init()

    def __call__(this):
        return this.cast()

    def sync_sp(this, c):
        this.sp = c.sp

    def init(this):
        pass

    def charge(this, sp):
        this.charged = min(this.sp, this.charged + sp)
        if this.charged >= this.sp:
            this.skill_charged()
        # if this.charged > this.sp:  # should be
        # this.charged = this.sp

    def cb_silence_end(this, e):
        if loglevel >= 2:
            log('silence', 'end')
        this._static.silence = 0
        this.silence_end_event()

    def check(this):
        if this.sp == 0:
            return 0
        elif this._static.silence == 1:
            return 0
        elif this.charged >= this.sp:
            return 1
        else:
            return 0

    def cast(this):
        if not this.check():
            return 0
        else:
            if not this.ac():
                return 0
            this.charged = 0
            this._static.s_prev = this.name
            # Even if animation is shorter than 1.9, you can't cast next skill before 1.9
            this.silence_end_timer.on(this.silence_duration)
            this._static.silence = 1
            if loglevel >= 2:
                log('silence', 'start')
            return 1


#    def ac(this):
#        #this.cast_event = Event(this.name+'_cast')
#        #this.cast_event()
#        return 1
#
class Actionparts(object):
    def __init__(this, host, timing):
        this.atype = host.atype
        this.timing = timing
        this.timer = []
        idx = 0
        for i in timing:
            idx += 1
            t = Timer(this.cb, i)
            t.idx = idx
            this.timer.append(t)

    def on(this):
        for i in this.timer:
            i.on()

    def off(this):
        for i in this.timer:
            i.off()

    def cb(this, t):
        this.host._act(t.idx)


class Action(object):
    _static = Static({
        'prev': 0,
        'doing': 0,
        'spd_func': 0,
    })

    name = '_Action'
    index = 0
    recover_start = 0
    startup_start = 0
    _startup = 0
    _recovery = 0
    status = -2  # -2nop -1startup 0doing 1recovery
    idle = 0

    class Nop(object):
        name = '__idle__'
        index = 0
        status = -2
        idle = 1

    nop = Nop()

    def __init__(this, name=None, conf=None, act=None):  ## can't change name after this
        if name != None:
            if type(name) == tuple:
                this.name = name[0]
                this.index = name[1]
            else:
                this.name = name
                this.index = 0
            this.atype = this.name

        if conf != None:
            this.conf = conf
            this.conf.sync_action = this.sync_config
        else:
            this.conf = Conf()
            this.conf.sync_action = this.sync_config

        if act != None:
            this.act = act

        if this._static.spd_func == 0:
            this._static.spd_func = this.nospeed
        if this._static.doing == 0:
            this._static.doing = this.nop
        if this._static.prev == 0:
            this._static.prev = this.nop

        this.cancel_by = []
        this.interrupt_by = []

        this.startup_timer = Timer(this._cb_acting)
        this.recovery_timer = Timer(this._cb_act_end)
        this.idle_event = Event('idle')
        this.act_event = Event(this.name)
        this.realtime()

    def sync_config(this, c):
        this._startup = c.startup
        this._recovery = c.recovery
        this._active = c.active

    def __call__(this):
        return this.tap()

    def getdoing(this):
        return this._static.doing

    def _setdoing(this):
        this._static.doing = this

    def getprev(this):
        return this._static.prev

    def _setprev(this):
        this._static.prev = this._static.doing

    def rt_tap(this):
        if this.rt_name != this.name:
            if this.atype == this.rt_name:
                this.atype = this.name
            this.rt_name = this.name
            this.act_event = Event(this.name)
        return this.o_tap()

    def realtime(this):
        this.rt_name = this.name
        this.tap, this.o_tap = this.rt_tap, this.tap

    def getrecovery(this):
        return this._recovery / this.speed()

    def getstartup(this):
        return this._startup / this.speed()

    def nospeed(this):
        return 1

    def speed(this):
        return this._static.spd_func()

    def _cb_acting(this, e):
        if this.getdoing() == this:
            this.status = 0
            this._act(1)
            this.status = 1
            this.recover_start = now()
            this.recovery_timer.on(this.getrecovery())

    def _cb_act_end(this, e):
        if this.getdoing() == this:
            if loglevel >= 2:
                log('ac_end', this.name)
            this.status = -2
            this._setprev()  # turn this from doing to prev
            this._static.doing = this.nop
            this.idle_event()

    def _act(this, partidx):
        this.idx = partidx
        if loglevel >= 2:
            log('act', this.name)
        this.act(this)

    def act(this, action):
        this.act_event.name = this.name
        this.act_event.idx = this.idx
        this.act_event()

    def tap(this):
        doing = this._static.doing

        if doing.idle:
            if loglevel >= 2:
                log('tap', this.name, this.atype + '\t', 'idle:%d' % doing.status)
        else:
            if loglevel >= 2:
                log('tap', this.name, this.atype + '\t', 'doing ' + doing.name + ':%d' % doing.status)

        if doing == this:  # self is doing
            return 0

        # if doing.idle # idle
        #    pass
        if not doing.idle:  # doing != this
            if doing.status == -1:  # try to interrupt an action
                if this.atype in doing.interrupt_by:  # can interrupt action
                    doing.startup_timer.off()
                    log('interrupt', doing.name, 'by ' + this.name + '\t',
                        'after %.2fs' % (now() - doing.startup_start))
                else:
                    return 0
            elif doing.status == 1:  # try to cancel an action
                if this.atype in doing.cancel_by:  # can interrupt action
                    doing.recovery_timer.off()
                    log('cancel', doing.name, 'by ' + this.name + '\t', 'after %.2fs' % (now() - doing.recover_start))
                else:
                    return 0
            elif doing.status == 0:
                raise Exception('err in action tap()')
            this._setprev()
        this.status = -1
        this.startup_start = now()
        this.startup_timer.on(this.getstartup())
        this._setdoing()
        if now() <= 3:
            log('debug', 'tap,startup', this.getstartup())
        return 1


class X(Action):
    def __init__(this, name, conf, act=None):
        Action.__init__(this, name, conf, act)
        this.atype = 'x'
        this.interrupt_by = ['fs', 's', 'dodge']
        this.cancel_by = ['fs', 's', 'dodge']

    def realtime(this):
        this.act_event = Event('x')
        this.act_event.name = this.name
        this.rt_name = this.name
        this.tap, this.o_tap = this.rt_tap, this.tap

    def rt_tap(this):
        if this.rt_name != this.name:
            if this.atype == this.rt_name:
                this.atype = this.name
            this.rt_name = this.name
            this.act_event.name = this.name
        return this.o_tap()


class Fs(Action):
    def __init__(this, name, conf, act=None):
        Action.__init__(this, name, conf, act)
        this.atype = 'fs'
        this.interrupt_by = ['s']
        this.cancel_by = ['s', 'dodge']

    def sync_config(this, c):
        this._charge = c.charge
        this._startup = c.startup
        this._recovery = c.recovery
        this._active = c.active

    def getstartup(this):
        return this._charge + (this._startup / this.speed())

    def realtime(this):
        this.act_event = Event('fs')
        this.act_event.name = this.name


class Fs_group(object):
    def __init__(this, name, conf, act=None):
        this.actions = {}
        this.conf = conf
        fsconf = conf.fs
        xnfsconf = [fsconf, fsconf, fsconf, fsconf, fsconf, fsconf]

        for i in range(5):
            xnfs = 'x%dfs' % (i + 1)
            if xnfs in this.conf:
                xnfsconf[i] += this.conf[xnfs]

        if 'dfs' in this.conf:
            xnfsconf[5] += this.conf.dfs

        this.add('default', Fs(name, fsconf, act))
        this.add('x1', Fs(name, xnfsconf[0], act))
        this.add('x2', Fs(name, xnfsconf[1], act))
        this.add('x3', Fs(name, xnfsconf[2], act))
        this.add('x4', Fs(name, xnfsconf[3], act))
        this.add('x5', Fs(name, xnfsconf[4], act))
        this.add('dodge', Fs(name, xnfsconf[5], act))

    def add(this, name, action):
        this.actions[name] = action

    def __call__(this, before):
        if before in this.actions:
            return this.actions[before]()
        else:
            return this.actions['default']()


class S(Action):
    def __init__(this, name, conf, act=None):
        Action.__init__(this, name, conf, act)
        this.atype = 's'
        this.interrupt_by = []
        this.cancel_by = []

    def realtime(this):
        this.act_event = Event('s')
        this.act_event.name = this.name


class Dodge(Action):
    def __init__(this, name, conf, act=None):
        Action.__init__(this, name, conf, act)
        this.atype = 'dodge'
        this.cancel_by = ['fs', 's']

    def realtime(this):
        this.act_event = Event('dodge')
        this.act_event.name = this.name

    def getstartup(this):
        return this._startup

    def getrecovery(this):
        return this._recovery


class Adv(object):
    Timer = Timer
    Event = Event
    Listener = Listener
    # vvvvvvvvv rewrite this to provide advanced tweak vvvvvvvvvv
    name = None

    def s1_proc(this, e):
        pass

    def s2_proc(this, e):
        pass

    def s3_proc(this, e):
        pass

    def fs_proc(this, e):
        pass

    def dmg_proc(this, name, amount):
        pass

    def s1_before(this, e):
        pass

    def s2_before(this, e):
        pass

    def s3_before(this, e):
        pass

    def fs_before(this, e):
        pass

    def dmg_before(this, name, amount):
        pass

    def speed(this):
        return 1

    def init(this):
        pass

    def equip(this):
        pass

    def setup(this):
        pass

    def d_acl(this):
        pass

    def d_slots(this):
        pass

    def slot_backdoor(this):
        pass

    def acl_backdoor(this):
        pass

    def prerun(this):
        pass

    # ^^^^^^^^^ rewrite these to provide advanced tweak ^^^^^^^^^^

    comment = ''
    # x_status = (0,0)
    mods = []
    conf = None
    a1 = None
    a2 = None
    a3 = None

    conf_default = Conf()

    # conf_default.latency.x = 0.05
    # conf_default.latency.sp = 0.05
    # conf_default.latency.default = 0.05
    # conf_default.latency.idle = 0

    # Latency represents the human response time, between when an event
    # triggers a "think" event, and when the human actually triggers
    # the input.  Right now it's set to zero, which means "perfect"
    # response time (which is unattainable in reality.)
    conf_default.latency = Conf({'x': 0, 'sp': 0, 'default': 0, 'idle': 0})

    conf_default.s1 = Conf({'dmg': 0, 'sp': 0, 'startup': 0.1, 'recovery': 1.9})
    conf_default.s2 = Conf({'dmg': 0, 'sp': 0, 'startup': 0.1, 'recovery': 1.9})
    conf_default.s3 = Conf({'dmg': 0, 'sp': 0, 'startup': 0.1, 'recovery': 1.9})
    conf_default.dodge = Conf({'startup': 0, 'recovery': 43.0 / 60.0})
    conf_default.fsf = Conf({'startup': 0, 'recovery': 41.0 / 60.0})
    # conf_default.slots = Conf({'w':None,'d':None,'a':None})
    conf_default.slots = Conf()

    conf_default.acl = '''
        `s1
        `s2
        `s3
    '''

    acl_prepare_default = '''
        #pin=e.pin
        #dname=e.dname
        #dstat=e.dstat
        #didx=e.didx
        #prev = this.action.getprev()
        #pname=prev.name
        #pidx=prev.index
        #pstat=prev.status
        #rotation = this.rotation

        #xseq = -1
        #if dname[0] == 'x': xseq = didx
        #if dstat == -2: xseq = 0
        #seq = xseq

        #cancel=0
        #x=0
        #fsc=0
        #if pin == 'x': \n    x=didx\n    cancel=1\n    x_cancel=1
        #if pin == 'fs':\n    fsc=1\n    cancel=1

        #s=0
        #sx=0
        #if pin[0] == 's' and pin[1] != 'p':\n    s=int(pin[1])
        #if pin[-2:] == '-x':\n    s=int(pin[1])\n    sx=s\n

        #sp=0
        #if pin == 'sp': sp=dname

        #s1=this.s1
        #s2=this.s2
        #s3=this.s3
        #fs=this.fs
        #fsf=this.fsf
        #dodge=this.dodge
        #dragon=this.dragonform
    '''

    # if pin[-2:] == '-x':\n    s=pidx\n    sx=pidx\n    print(sx)\n    print(pin)\n    errrrrrrr()

    def doconfig(this):

        # set buff
        this.action = Action()
        this.action._static.spd_func = this.speed
        # set buff
        this.buff = Buff()
        this.all_buffs = []
        this.buff._static.all_buffs = this.all_buffs
        this.buff._static.time_func = this.bufftime
        # set modifier
        this.modifier = Modifier(0, 0, 0, 0)
        this.all_modifiers = ModifierDict()
        this.modifier._static.all_modifiers = this.all_modifiers
        this.modifier._static.g_condition = this.condition

        # set ex
        this.ex = this.slots.c.ex

        # init actions
        # this.a_fs
        # fsconf = this.conf.fs
        # xnfsconf = [fsconf,fsconf,fsconf,fsconf,fsconf,fsconf]

        # for i in range(5):
        #     xnfs = 'x%dfs'%(i+1)
        #     if xnfs in this.conf:
        #         xnfsconf[i] += this.conf[xnfs]

        # if 'dfs' in this.conf:
        #     xnfsconf[5] += this.conf.dfs

        this.a_x1 = X(('x1', 1), this.conf.x1)
        this.a_x2 = X(('x2', 2), this.conf.x2)
        this.a_x3 = X(('x3', 3), this.conf.x3)
        this.a_x4 = X(('x4', 4), this.conf.x4)
        this.a_x5 = X(('x5', 5), this.conf.x5)

        this.a_fs = Fs_group('fs', this.conf)
        this.a_fsf = Fs('fsf', this.conf.fsf)
        this.a_fsf.act_event = Event('none')

        this.a_dodge = Dodge('dodge', this.conf.dodge)

        # skill init
        this.s1 = Skill('s1', this.conf.s1)
        this.s2 = Skill('s2', this.conf.s2)
        this.s3 = Skill('s3', this.conf.s3)

        if this.conf.xtype == 'ranged':
            this.l_x = this.l_range_x
            this.l_fs = this.l_range_fs
            # this.fs_success = this.range_fs_sucess
        elif this.conf.xtype == 'melee':
            this.l_x = this.l_melee_x
            this.l_fs = this.l_melee_fs
            # this.fs_success = this.melee_fs_success

        # set cmd
        this.x1 = this.a_x1
        this.x2 = this.a_x2
        this.x3 = this.a_x3
        this.x4 = this.a_x4
        this.x5 = this.a_x5
        # this.fs = this.a_fs
        this.fsf = this.a_fsf
        this.dodge = this.a_dodge

        this.hits = 0
        this.dragonform = None

    def afflic_condition(this):
        if 'afflict_res' in this.conf:
            res_conf = this.conf.afflict_res
            for afflic in AFFLICT_LIST:
                if afflic in res_conf and 0 <= res_conf[afflic] <= 100:
                    if this.condition('{} {} res'.format(res_conf[afflic], afflic)):
                        vars(this.afflics)[afflic].resist = res_conf[afflic]
                    else:
                        vars(this.afflics)[afflic].resist = 100

    def sim_affliction(this):
        if 'sim_afflict' in this.conf:
            t = int(this.conf.sim_afflict.time)
            if t > 0:
                # if this.condition('{} for {}s'.format(this.conf.sim_afflict.type, t)):
                aff = vars(this.afflics)[this.conf.sim_afflict.type]
                aff.on('simulated'.format(this.conf.sim_afflict.type), 200, 0, duration=t, iv=t)
                aff.states = None

    def sim_buffbot(this):
        if 'sim_buffbot' in this.conf:
            if 'debuff' in this.conf.sim_buffbot:
                value = -this.conf.sim_buffbot.debuff
                if this.condition('boss def {:+.0%}'.format(value)):
                    buff = this.Selfbuff('simulated_def', value, -1, mtype='def')
                    buff.on()
            if 'buff' in this.conf.sim_buffbot:
                if this.condition('team str {:+.0%}'.format(this.conf.sim_buffbot.buff)):
                    this.Selfbuff('simulated_att', this.conf.sim_buffbot.buff, -1).on()

    def sync_slot(this, conf_slots):
        # this.cmnslots(conf)
        # this.slots = slot.Slots()
        if now():
            print('cannot change slots after run')
            errrrrrrrrrrrr()
        if 'c' in conf_slots:
            this.slots.c = conf_slots.c
        elif not this.slots.c:
            this.slots.c = this.cmnslots.c

        if 'd' in conf_slots:
            this.slots.d = conf_slots.d
        elif not this.slots.d:
            this.slots.d = this.cmnslots.d

        if 'w' in conf_slots:
            this.slots.w = conf_slots.w
        elif not this.slots.w:
            this.slots.w = this.cmnslots.w

        if 'a' in conf_slots:
            this.slots.a = conf_slots.a
        elif not this.slots.a:
            this.slots.a = this.cmnslots.a
        # print this.slots

    def pre_conf(this):
        tmpconf = Conf()
        tmpconf += this.conf_default
        tmpconf += globalconf.get(this.name)
        tmpconf += Conf(this.conf)
        tmpconf(this.conf_init)
        this.conf = tmpconf

    def default_slot(this):
        from conf import slot_common
        this.cmnslots = slot.Slots()
        this.cmnslots.c.att = this.conf.c.att
        this.cmnslots.c.wt = this.conf.c.wt
        this.cmnslots.c.stars = this.conf.c.stars
        this.cmnslots.c.ele = this.conf.c.ele
        this.slot_common = slot_common.set
        this.slot_common(this.cmnslots)
        this.slots = this.cmnslots
        # print this.cmnslots

    def __init__(this, conf={}, cond=None):
        if not this.name:
            this.name = this.__class__.__name__
        this.Event = Event
        this.Buff = Buff
        this.Debuff = Debuff
        this.Selfbuff = Selfbuff
        this.Teambuff = Teambuff
        this.Modifier = Modifier
        this.Conf = Conf
        this.log = log

        this.conf_init = conf
        this.ctx = Ctx().on()
        this.condition = Condition(cond)
        # this.m_condition = m_condition
        # this.m_condition.set(cond)
        this._log = []
        loginit(this._log)

        this.s3_buff_list = []
        this.s3_buff = None

        if not this.conf:
            this.conf = Conf()
        this.pre_conf()

        # this.slots = slot.Slots()
        this.default_slot()

        # def slot_backdoor():
        #     pass
        # this.slot_backdoor = slot_backdoor

        this.conf.slot.sync_slot = this.sync_slot
        this.conf.slots.sync_slot = this.sync_slot

        if 1:
            this.crit_mod = this.solid_crit_mod
        else:
            this.crit_mod = this.rand_crit_mod

        this.skill = Skill()
        this._acl = None

        # set afflic
        this.afflics = Afflics()

        # this.classconf = this.conf
        this.init()

        # if type(this.conf).__name__ != 'Conf':
        #    this.pre_conf()
        #    this.conf.slot.sync_slot = this.sync_slot
        #    this.conf.slots.sync_slot = this.sync_slot

        # this.ctx.off()

    def dmg_mod(this, name):
        mod = 1
        if name[:2] == 'o_':
            name = name[2:]

        if name[0] == 's':
            return mod * this.mod('s')
        elif name[0:2] == 'fs':
            return mod * this.mod('fs')
        elif name[0] == 'x':
            return mod * this.mod('x')
        else:
            return mod

    def mod(this, mtype):
        return reduce(operator.mul, [this.sub_mod(mtype, order) for order in this.all_modifiers[mtype].keys()], 1)

    def sub_mod(this, mtype, morder):
        return 1 + sum([modifier.get() for modifier in this.all_modifiers[mtype][morder]])

    def l_have_speed(this, e):
        this.speed = this.have_speed
        this.action._static.spd_func = this.speed

    def have_speed(this):
        return min(this.mod('spd'), 1.50)

    def crit_mod(this):
        pass

    def solid_crit_mod(this):
        m = {'chance': 0, 'dmg': 0, 'damage': 0, 'passive': 0, 'rate': 0, }
        for order, modifiers in this.all_modifiers['crit'].items():
            for modifier in modifiers:
                if order in m:
                    m[order] += modifier.get()
                else:
                    raise ValueError(f"Invalid crit mod order {order}")
        chance = m['chance'] + m['passive'] + m['rate']
        if chance > 1:
            chance = 1
        cdmg = m['dmg'] + m['damage'] + 1.7
        average = chance * (cdmg - 1) + 1
        return average

    def rand_crit_mod(this):
        m = {'chance': 0, 'dmg': 0, 'damage': 0, 'passive': 0, 'rate': 0, }
        for order, modifiers in this.all_modifiers['crit'].items():
            for modifier in modifiers:
                if order in m:
                    m[order] += modifier.get()
                else:
                    raise ValueError(f"Invalid crit mod order {order}")
        chance = m['chance'] + m['passive'] + m['rate']
        if chance > 1:
            chance = 1
        cdmg = m['dmg'] + m['damage'] + 1.7
        r = random.random()
        if r < chance:
            return cdmg
        else:
            return 1

    def att_mod(this):
        att = this.mod('att')
        cc = this.crit_mod()
        k = this.killer_mod()
        return cc * att * k

    def killer_mod(this):
        rates = {
            'overdrive': Overdrive_Punisher.EFFICIENCY
        }
        for afflic in AFFLICT_LIST:
            rate = vars(this.afflics)[afflic].get()
            if rate > 0:
                rates[afflic] = rate
        total = 0
        rate_list = list(rates.items())
        for mask in product(*[[0, 1]] * len(rate_list)):
            p = 1.0
            modifiers = defaultdict(lambda: set())
            for i, on in enumerate(mask):
                cond = rate_list[i]
                cond_name = cond[0]
                cond_p = cond[1]
                if on:
                    p *= cond_p
                    for order, mods in this.all_modifiers[f"{cond_name}_killer"].items():
                        for mod in mods:
                            modifiers[order].add(mod)
                else:
                    p *= 1 - cond_p
            total += p * reduce(operator.mul, [1 + sum([mod.get() for mod in order]) for order in modifiers.values()],
                                1.0)
        return total

    def def_mod(this):
        m = this.mod('def')
        if m < 0.5:
            return 0.5
        else:
            return m

    def sp_mod(this, name):
        sp_mod = 1
        for order, modifiers in this.all_modifiers['sp'].items():
            if order == 'fs':
                if name.startswith('fs'):
                    sp_mod += sum([modifier.get() for modifier in modifiers])
            else:
                sp_mod += sum([modifier.get() for modifier in modifiers])
        return sp_mod

    def sp_val(this, param):
        if isinstance(param, str):
            return this.ceiling(this.float_problem(this.conf[param + '.sp'] * this.float_problem(this.sp_mod(param))))
        elif isinstance(param, int) and 1 <= param <= 5:
            return sum([this.ceiling(
                this.float_problem(this.conf['x{}.sp'.format(x)] * this.float_problem(this.sp_mod('x{}'.format(x)))))
                for x in range(1, param + 1)])

    def bufftime(this):
        return this.mod('buff')

    def have_buff(this, name):
        for b in this.all_buffs:
            if b.name.startswith(name) and b.get():
                return True
        return False

    def l_idle(this, e):
        """
        Listener that is called when there is nothing to do.
        """
        this.think_pin('idle')
        prev = this.action.getprev()
        if prev.name[0] == 's':
            this.think_pin(prev.name)
        if this.skill._static.first_x_after_s:
            this.skill._static.first_x_after_s = 0
            s_prev = this.skill._static.s_prev
            this.think_pin('%s-x' % s_prev)
        this.x()

    def getxseq(this):
        doing = this.action.getdoing()
        if doing.name[0] == 'x':
            return doing.index, doing.status
        else:
            return doing.name, doing.index

    def getprev(this):
        prev = this.action.getprev()
        return prev.name, prev.index, prev.status

    def fs(this):
        doing = this.action.getdoing()
        return this.a_fs(doing.name)

    def x(this):
        prev = this.action.getprev()
        x_next = 1
        if prev.name[0] == 'x':
            if prev.index != 5:
                x_next = prev.index + 1

        a = getattr(this, 'x%d' % x_next)()
        return 1

    def l_range_x(this, e):
        xseq = e.name
        dmg_coef = this.conf['%s.dmg' % xseq]
        sp_gain = this.conf['%s.sp' % xseq]
        if xseq == 'x5':
            log('x', '%s' % xseq, 0, '-------------------------------------c5')
        else:
            log('x', '%s' % xseq, 0)

        missile_timer = Timer(this.cb_missile, this.conf['missile_iv'][xseq])
        missile_timer.dname = '%s_missile' % xseq
        missile_timer.amount = dmg_coef
        missile_timer.samount = sp_gain
        missile_timer()

        this.think_pin('x')

    def cb_missile(this, t):
        this.update_hits(t.dname)
        this.dmg_make(t.dname, t.amount)
        this.charge(t.dname, t.samount)

    def l_melee_x(this, e):
        xseq = e.name
        dmg_coef = this.conf['%s.dmg' % xseq]
        sp = this.conf['%s.sp' % xseq]
        if xseq == 'x5':
            log('x', '%s' % xseq, 0, '-------------------------------------c5')
        else:
            log('x', '%s' % xseq, 0)
        this.update_hits(xseq)
        this.dmg_make('%s' % xseq, dmg_coef)
        this.think_pin('x')
        this.charge('%s' % xseq, sp)

    def dodge(this):
        return this.a_dodge()

    def l_dodge(this, e):
        log('dodge', '-')
        this.think_pin('dodge')

    def update_hits(this, name):
        if '_missile' in name:
            name = name.split('_')[0]
        try:
            hit = this.conf['{}.hit'.format(name)]
            if hit >= 0:
                this.hits += hit
                # print('debug', 'combo add', name, '{} -> {}'.format(hit, this.hits))
            else:
                this.hits = -hit
                # print('debug', 'combo break', name, '{} -> {}'.format(hit, this.hits))
        except AttributeError:
            pass

    def run(this, d=300):
        global loglevel
        if not loglevel:
            loglevel = 0

        this.ctx.on()

        this.doconfig()

        this.l_idle = Listener('idle', this.l_idle)
        this.l_x = Listener('x', this.l_x)
        this.l_dodge = Listener('dodge', this.l_dodge)
        this.l_fs = Listener('fs', this.l_fs)
        this.l_s = Listener('s', this.l_s)
        # this.l_x           = Listener(['x','x1','x2','x3','x4','x5'],this.l_x)
        # this.l_fs          = Listener(['fs','x1fs','x2fs','x3fs','x4fs','x5fs'],this.l_fs)
        # this.l_s           = Listener(['s','s1','s2','s3'],this.l_s)
        this.l_silence_end = Listener('silence_end', this.l_silence_end)
        this.l_dmg_make = Listener('dmg_make', this.l_dmg_make)
        this.l_true_dmg = Listener('true_dmg', this.l_true_dmg)
        this.l_dmg_formula = Listener('dmg_formula', this.l_dmg_formula)
        this.l_have_speed = Listener('speed', this.l_have_speed)

        this.ctx.on()

        for i in this.conf.mod:
            v = this.conf.mod[i]
            if type(v) == tuple:
                this.slots.c.mod.append(v)
            if type(v) == list:
                this.slots.c.mod += v
        if this.a1:
            this.slots.c.a.append(this.a1)
        if this.a2:
            this.slots.c.a.append(this.a2)
        if this.a3:
            this.slots.c.a.append(this.a3)

        this.equip()
        this.setup()

        this.d_slots()
        this.slot_backdoor()
        # print this.slots
        this.base_att = int(this.slots.att(globalconf.forte))
        this.slots.oninit(this)

        this.prerun()
        this.afflic_condition()
        this.sim_affliction()
        this.sim_buffbot()

        this.d_acl()
        this.acl_backdoor()

        if not this._acl:
            this._acl_str = core.acl.acl_func_str(this.conf.acl)
            from core.acl import do_act
            this._acl = do_act

        this.displayed_att = int(this.base_att * this.mod('att'))

        if type(this.conf.rotation) == list:
            for i in this.conf.rotation:
                i = i.lower()
            this.get_next_act = this.get_next_act_from_list
        elif type(this.conf.rotation) == str:
            this.conf.rotation = this.conf.rotation.lower()

        if type(this.conf.rotation_init) == list:
            for i in this.conf.rotation_init:
                i = i.lower()
            this.get_next_act = this.get_next_act_from_list
        elif type(this.conf.rotation_init) == str:
            this.conf.rotation_init = this.conf.rotation_init.lower()

        this.rotation_init = 0
        if type(this.conf.rotation_init) in [str, list]:
            this.rotation_init = 1
            this.rotation_repeat = this.conf.rotation
            this.conf.rotation = this.conf.rotation_init

        if type(this.conf.rotation) in [str, list]:
            this.rotation_stat = 0
            this.xstat_prev = ''
            this.act_next = 0
            this.rt_len = len(this.conf.rotation)
            this.o_rt = this.conf.rotation

        Event('idle')()
        this.debug()
        end = Timeline.run(d)
        log('sim', 'end')

        for aff, up in this.afflics.get_uptimes().items():
            if up > 0.10:
                if len(this.comment) > 0:
                    this.comment += '; '
                this.comment += '{:.0%} {} uptime'.format(up, aff)

        return end

    def debug(this):
        pass

    def think_pin(this, pin):
        # pin as in "signal", says what kind of event happened
        def cb_think(t):
            if loglevel >= 2:
                log('think', t.pin, t.dname)
            this._acl(this, t)

        if pin in this.conf.latency:
            latency = this.conf.latency[pin]
        else:
            latency = this.conf.latency.default

        t = Timer(cb_think).on(latency)
        doing = this.action.getdoing()
        t.pin = pin
        t.dname = doing.name
        t.dstat = doing.status
        t.didx = doing.index

    def l_silence_end(this, e):
        doing = this.action.getdoing()
        sname = this.skill._static.s_prev
        if doing.name[0] == 'x':
            this.skill._static.first_x_after_s = 1
        else:
            this.think_pin(sname + '-x')  # best choice
        this.think_pin(sname)
        # if doing.name[0] == 's':
        #   no_deed_to_do_anythin

    # implement single float of c in python
    def float_problem(this, a):
        return floatsingle.tofloat(a)

    # this ceiling is the true ceiling
    def ceiling(this, a):
        b = int(a)
        if b == a:
            return b
        else:
            return b + 1

    def charge_p(this, name, sp):
        percent = sp
        this.s1.charge(this.ceiling(this.conf.s1.sp * percent))
        this.s2.charge(this.ceiling(this.conf.s2.sp * percent))
        this.s3.charge(this.ceiling(this.conf.s3.sp * percent))
        log('sp', name, '{:.0f}%   '.format(percent * 100), '%d/%d, %d/%d, %d/%d' % ( \
            this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp))
        this.think_pin('prep')

    def charge(this, name, sp):
        # sp should be integer
        sp = int(sp) * this.float_problem(this.sp_mod(name))
        sp = this.float_problem(sp)
        sp = this.ceiling(sp)
        this.s1.charge(sp)
        this.s2.charge(sp)
        this.s3.charge(sp)
        this.think_pin('sp')
        log('sp', name, sp, '%d/%d, %d/%d, %d/%d' % ( \
            this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp))

    def l_dmg_formula(this, e):
        name = e.dname
        dmg_coef = e.dmg_coef
        if hasattr(e, 'dtype'):
            name = e.dtype
        if 'modifiers' in e.__dict__:
            if e.modifiers != None and e.modifiers != 0:
                this.all_modifiers = e.modifiers
        e.dmg = this.dmg_formula(name, dmg_coef)
        this.all_modifiers = this.modifier._static.all_modifiers
        e.ret = e.dmg
        return

    def dmg_formula(this, name, dmg_coef):
        att = 1.0 * this.att_mod() * this.base_att
        armor = 10 * this.def_mod()
        # return float(dmg_coef) * this.dmg_mod(name) * this.att_mod() / this.def_mod()
        # return float(dmg_coef) * this.dmg_mod(name) * this.def_mod()
        return 5.0 / 3 * dmg_coef * this.dmg_mod(name) * att / armor * 1.5  # true formula
        # return att/armor * dmg_coef * this.dmg_mod(name)

    def l_true_dmg(this, e):
        log('dmg', e.dname, e.count, e.comment)

    def l_dmg_make(this, e):
        if 'dtype' in vars(e):
            this.dmg_make(e.dname, e.dmg_coef, e.dtype)
        else:
            this.dmg_make(e.dname, e.dmg_coef)

    def dmg_make(this, name, dmg_coef, dtype=None, fixed=False):
        if dtype == None:
            dtype = name
        count = this.dmg_formula(dtype, dmg_coef) if not fixed else dmg_coef
        log('dmg', name, count)
        this.dmg_proc(name, count)
        return count

    def dmg_make_withspshow(this, name, dmg_coef, dtype=None):
        if dtype == None:
            dtype = name

        count = this.dmg_formula(dtype, dmg_coef)
        this.dmg_before(name, count)

        if name[0] == 'x':
            spgain = this.conf[name[:2] + '.sp']
            log('dmg', name, count, '%d/%d, %d/%d, %d/%d (+%d)' % ( \
                this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp, spgain))
        elif name[:2] == 'fs':
            spgain = this.conf['fs.sp']
            log('dmg', name, count, '%d/%d, %d/%d, %d/%d (+%d)' % ( \
                this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp, spgain))
        else:
            spgain = 0
            if name[:2] + '.sp' in this.conf:
                spgain = this.conf[name[:2] + '.sp']
            log('dmg', name, count, '%d/%d, %d/%d, %d/%d (-%d)' % ( \
                this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp, spgain))

        this.dmg_proc(name, count)

    def l_melee_fs(this, e):
        log('fs', 'succ')
        dmg_coef = this.conf.fs.dmg
        this.fs_before(e)
        this.update_hits('fs')
        this.dmg_make('fs', dmg_coef)
        this.fs_proc(e)
        this.think_pin('fs')
        this.charge('fs', this.conf.fs.sp)

    def l_range_fs(this, e):
        log('fs', 'succ')
        this.fs_before(e)
        this.update_hits('fs')
        dmg_coef = this.conf['fs.dmg']
        sp_gain = this.conf['fs.sp']
        missile_timer = Timer(this.cb_missile, this.conf['missile_iv']['fs'])
        missile_timer.dname = 'fs_missile'
        missile_timer.amount = dmg_coef
        missile_timer.samount = sp_gain
        missile_timer()
        this.fs_proc(e)
        this.think_pin('fs')

    def l_s(this, e):
        this.update_hits(e.name)

        prev, index, stat = this.getprev()
        if prev == 'fs':
            log('cast', e.name, 0, '<cast> %d/%d, %d/%d, %d/%d (%s after fs)' % ( \
                this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp, e.name))
        elif prev[0] == 'x':
            log('cast', e.name, 0, '<cast> %d/%d, %d/%d, %d/%d (%s after c%s)' % ( \
                this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp, e.name, index))
        else:
            log('cast', e.name, 0, '<cast> %d/%d, %d/%d, %d/%d (%s after %s)' % ( \
                this.s1.charged, this.s1.sp, this.s2.charged, this.s2.sp, this.s3.charged, this.s3.sp, e.name, prev))

        dmg_coef = this.conf[e.name + '.dmg']
        func = e.name + '_before'
        tmp = getattr(this, func)(e)
        if tmp != None:
            dmg_coef = tmp
        if dmg_coef:
            this.dmg_make(e.name, dmg_coef)

        if 'buff' in this.conf[e.name] and this.conf[e.name + '.buff'] is not None:
            buffarg = this.conf[e.name + '.buff']
            if e.name == 's3':
                if len(this.s3_buff_list) == 0:
                    for ba in buffarg:
                        if ba is not None:
                            buff = this.do_buff(e, ba)
                            this.s3_buff_list.append(buff)
                        else:
                            this.s3_buff_list.append(None)
                    if this.s3_buff_list[0] is not None:
                        this.s3_buff_list[0].on()
                        this.s3_buff = this.s3_buff_list[0]
                else:
                    this.s3_buff = None
                    for buff in this.s3_buff_list:
                        if buff is not None:
                            if buff.get():
                                buff.off()
                            else:
                                buff.on()
                                this.s3_buff = buff
            else:
                this.do_buff(e, buffarg).on()

        func = e.name + '_proc'
        getattr(this, func)(e)

    @staticmethod
    def do_buff(e, buffarg):
        wide = buffarg[0]
        buffarg = buffarg[1:]
        buff = None
        if wide == 'team':
            buff = Teambuff(e.name, *buffarg)
        elif wide == 'self':
            buff = Selfbuff(e.name, *buffarg)
        elif wide == 'debuff':
            buff = Debuff(e.name, *buffarg)
        elif wide == 'spd':
            buff = Spdbuff(e.name, *buffarg)
        else:
            buff = Buff(e.name, *buffarg)
        return buff

    def rotation(this):
        r = 0
        if not this.act_next:
            this.act_next = this.get_next_act()
        anext = this.act_next

        doing = this.action.getdoing()
        dname = doing.name
        dstat = doing.status
        # didx = doing.index

        if dname[0] != 'x' and dstat != 1:
            return 0
        # print(anext)
        # print(dname, anext, dstat)
        if this.xstat_prev != dname:
            this.xstat_prev = ''
        if anext[0] in ['c', 'x']:
            # log('debug','-',this.xstat_prev,dname)
            if dname != 'x' + anext[1]:
                r = 0
            elif dstat == 1 and this.xstat_prev == '':
                this.xstat_prev = dname
                # log('debug','rotation',dname)
                r = 1
            else:
                r = 0
            this.x()
        elif anext[0] == 's':
            # print(dname, anext)
            r = vars(this)[anext]()
        elif anext == 'fs':
            r = this.fs()
            # r = this.fs()
        elif anext in ['dodge', 'd']:
            r = this.dodge()
        elif anext == 'dragon':
            r = this.dragonform()
        elif anext == 'end':
            # def end(foo):
            #    Timeline.stop()
            ##Listener('idle',end).on()
            # Timer(end).on()
            Timeline.stop()
        if r:
            this.act_next = this.get_next_act()
        return r

    def get_next_act_from_list(this):
        p = this.rotation_stat
        rt = this.conf.rotation
        if this.o_rt != rt:
            print('cannot change rotation after run')
            errrrrrrrrrrrrrrrrr()
        ret = ''
        ret += rt[p]
        p += 1
        if p >= this.rt_len:
            p = 0
        this.rotation_stat = p
        return ret.lower()

    def get_next_act(this):
        p = this.rotation_stat
        rt = this.conf.rotation

        if this.o_rt != rt:
            print('cannot change rotation after run')
            errrrrrrrrrrrrrrrrr()
        ret = ''
        while (1):
            if p >= this.rt_len:
                this.rotation_reset()
                rt = this.conf.rotation
                p = 0
            c = ord(rt[p])
            if c > ord('a') and c < ord('z'):
                break
            elif c > ord('A') and c < ord('Z'):
                break
            elif c > ord('0') and c < ord('9'):
                break
            else:
                p += 1
        if rt[p] == 'c':
            xidx = int(rt[p + 1])
            if xidx > 5 or xidx < 1:
                print(rt + '\nlocation:%d,%s' % (p + 1, xidx))
                errrrrrrrrrrrrrrrr()
            ret += rt[p:p + 2]
            p += 2
        elif rt[p] in ['1', '2', '3', '4', '5'] and rt[p + 1] in ['x', 'c']:
            xidx = int(rt[p])
            ret += 'c' + rt[p]
            p += 2
        elif rt[p] == 's':
            sidx = int(rt[p + 1])
            if sidx > 3 or sidx < 1:
                print(rt + '\nlocation:%d,%s' % (p + 1, sidx))
                errrrrrrrrrrrrrrrr()
            ret += rt[p:p + 2]
            p += 2
        elif rt[p:p + 2] == 'fs':
            ret = 'fs'
            p += 2
        elif rt[p:p + 6] == 'dragon':
            ret = 'dragon'
            p += 6
        elif rt[p] == 'd':
            ret = 'dodge'
            p += 1
        elif rt[p:p + 3] == 'end':
            ret = 'end'
            p += 3
        else:
            print(rt + '\nlocation:%d' % (p))
            print(rt[p])
            errrrrrrrrrrrrrrrrrr()

        if p >= this.rt_len:
            this.rotation_reset()
            p = 0
        this.rotation_stat = p
        return ret

    def rotation_reset(this):
        if this.rotation_init:
            this.rotation_init = 0
            this.conf.rotation = this.rotation_repeat
            this.rt_len = len(this.conf.rotation)
            this.o_rt = this.conf.rotation


if __name__ == '__main__':
    print('to use adv_test')
