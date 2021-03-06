from core.advbase import Fs_group, X
from core.timeline import Listener
from core.log import log
from core.config import Conf

class Fs_alt:
    def __init__(self, adv, conf, fs_proc=None):
        self.adv = adv
        self.a_fs_og = adv.a_fs
        self.conf_og = adv.conf
        self.fs_proc_og = adv.fs_proc
        self.conf_alt = adv.conf + Conf(conf)
        self.a_fs_alt = Fs_group('fs_alt', self.conf_alt)
        self.fs_proc_alt = fs_proc
        self.uses = 0

    def fs_proc(self, e):
        if callable(self.fs_proc_alt):
            self.fs_proc_alt(e)
        self.uses -= 1
        if self.uses == 0:
            self.off()

    def on(self, uses = 1):
        log('debug', 'fs_alt on', uses)
        self.uses = uses
        self.adv.a_fs = self.a_fs_alt
        self.adv.conf = self.conf_alt
        self.adv.fs_proc = self.fs_proc

    def off(self):
        log('debug', 'fs_alt off', 0)
        self.uses = 0
        self.adv.a_fs = self.a_fs_og
        self.adv.conf = self.conf_og
        self.adv.fs_proc = self.fs_proc_og

    def get(self):
        return self.uses != 0

class X_alt:
    def __init__(self, adv, name, conf, x_proc=None, no_fs=False):
        conf = Conf(conf)
        self.adv = adv
        self.name = name
        self.x_og = adv.x
        self.a_x_alt = {}
        if x_proc:
            self.x_proc = x_proc
            self.l_x_alt = Listener('x', self.l_x).off()
        else:
            self.l_x_alt = None
        self.no_fs = no_fs
        self.fs_og = adv.fs
        self.xmax = 1
        n = 'x{}'.format(self.xmax)
        while n in conf:
            self.a_x_alt[n] = X(n, conf[n])
            self.xmax += 1
            n = 'x{}'.format(self.xmax)
        self.xmax -= 1
        self.active = False

    def x_alt(self):
        x_prev = self.adv.action.getprev()
        if x_prev.name in self.a_x_alt and x_prev.index < self.xmax:
            x_next = self.a_x_alt['x{}'.format(x_prev.index+1)]
        else:
            x_next = self.a_x_alt['x{}'.format(1)]
        return x_next()

    def l_x(self, e):
        self.x_proc(e)
        self.adv.think_pin('x')

    def fs_off(self):
        return False
    
    def on(self):
        log('debug', '{} x_alt on'.format(self.name))
        self.active = True
        self.adv.x = self.x_alt
        if self.l_x_alt:
            self.adv.l_x.off()
            self.l_x_alt.on()
        if self.no_fs:
            self.adv.fs = self.fs_off
    
    def off(self):
        log('debug', '{} x_alt off'.format(self.name))
        self.active = False
        self.adv.x = self.x_og
        if self.l_x_alt:
            self.l_x_alt.off()
            self.adv.l_x.on()
        if self.no_fs:
            self.adv.fs = self.fs_og