from ..kernels import KernelDot
from ..pipeline import Transform, Macro
from ..logger import log
import numpy as np
import multiprocessing as mp
import time
from .plugin_check import *

class KernelSmoothMatch(Transform):
    default_args = {
        "base_kernel": "xi.dot(xj.T)",
        "base_power": 3,
        "gamma": 1e-2,
        "epsilon": 1e-6
    }
    req_inputs = ("X",)
    allow_stream = ("K",)
    allow_params = ("X",)
    stream_kernel = ("K",)
    precompute = True
    verbose = True
    log = log
    def check_available():
        return check_gylmxx_available(__class__)
    def evaluate(self, X1, X2, symmetric):
        K = np.zeros((X1.shape[0], X2.shape[0]))
        for i in range(X1.shape[0]):
            xi = X1[i]
            for j in range(i if symmetric else 0, X2.shape[0]):
                xj = X2[j]
                if self.verbose: log << log.back << " Match %4d/%-4d   " % (i, j) << log.flush
                #kij = np.zeros((xi.shape[0], xj.shape[0]))
                #kij = xi.dot(xj.T)**self.args["base_power"]
                kij = eval(self.args["base_kernel"])**self.args["base_power"]
                pij = np.zeros_like(kij)
                gylm.smooth_match(pij, kij, kij.shape[0], kij.shape[1],
                    self.args["gamma"], self.args["epsilon"], self.verbose)
                K[i,j] = np.sum(kij*pij)
                if symmetric: K[j,i] = K[i,j]
        if self.verbose: log << log.endl
        return K
    def _fit(self, inputs):
        X = inputs["X"]
        K = self.evaluate(X, X, True)
        self.stream().put("K", K)
        self.params().put("X", np.copy(inputs["X"]))
    def _map(self, inputs):
        X1 = inputs["X"]
        X2 = self.params().get("X")
        K = self.evaluate(X1, X2, False)
        self.stream().put("K", K)

class GylmTransform(Transform):
    default_args = {
        "procs": 1,
        "rcut": 5.0,
        "rcut_width": 0.5,
        "nmax": 9,
        "lmax": 6,
        "sigma": 0.75,
        "part_sigma": 0.5,
        "wconstant": False,
        "wscale": 0.5,
        "wcentre": 0.5,
        "ldamp": 0.5,
        "power": True,
        "types": None,
        "normalize": True}
    req_inputs = ('configs',)
    allow_params = ("calc",)
    allow_stream = ("X",)
    stream_samples = ("X",)
    precompute = True
    log = None
    def check_available():
        return check_gylmxx_available(GylmAverage)
    def _setup(self, *args):
        self.procs = self.args.pop("procs", 1)
        if self.args["types"] is None:
            self.calc = None
        else:
            self.calc = gylm.GylmCalculator(**self.args)
    def _fit(self, inputs):
        if self.args["types"] is None:
            self.args["types"] = inputs["meta"]["elements"]
        self.calc = gylm.GylmCalculator(
            **self.args)
        self.params().put("calc", self.calc)
        self._map(inputs)

class GylmAverage(GylmTransform):
    def _map(self, inputs):
        X = gylm_evaluate(
            configs=inputs["configs"],
            dcalc=self.calc,
            reduce_molecular=np.sum,
            norm_molecular=True,
            centres=inputs.pop("centres", None))
        self.stream().put("X", X)

class GylmAtomic(GylmTransform):
    def _map(self, inputs):
        if self.procs == 1:
            X = gylm_evaluate(
                configs=inputs["configs"],
                dcalc=self.calc,
                reduce_molecular=None,
                norm_molecular=False,
                centres=inputs.pop("centres", None))
        else:
            X = gylm_evaluate_mp(
                configs=inputs["configs"],
                dcalc=self.calc,
                procs=self.procs,
                reduce_molecular=None,
                norm_molecular=False,
                centres=inputs.pop("centres", None))
        self.stream().put("X", X)

def gylm_evaluate_single(args):
    config = args["config"]
    dcalc = args["dcalc"]
    centres = args["centres"]
    if centres is None:
        heavy, types_centres, pos_centres = config.getHeavy()
    else:
        pos_centres = centres
    x = dcalc.evaluate(system=config, positions=pos_centres)
    return x

def gylm_evaluate_mp(
        configs,
        dcalc,
        procs,
        reduce_molecular=None,
        norm_molecular=False,
        centres=None):
    log = GylmTransform.log
    t0 = time.time()
    args_list = [ {
        "config": configs[i],
        "dcalc": dcalc,
        "centres": centres if centres is None else centres[i] } \
            for i in range(len(configs)) ]
    pool = mp.Pool(processes=procs)
    X = pool.map(gylm_evaluate_single, args_list)
    pool.close()
    for i in range(len(X)):
        x = X[i]
        if reduce_molecular is not None:
            x = reduce_molecular(x, axis=0)
        if norm_molecular:
            x = x/np.dot(x,x)**0.5
    t1 = time.time()
    if log:
        log << "[MP: Finished in %fs]" % (t1-t0) << log.flush
    X = np.array(X)
    return X

def gylm_evaluate(
        configs,
        dcalc,
        reduce_molecular=None,
        norm_molecular=False,
        centres=None):
    log = GylmTransform.log
    t0 = time.time()
    X = []
    for cidx, config in enumerate(configs):
        if log and log.verbose: log << log.back << \
            "%d/%d" % (cidx+1, len(configs)) << log.flush
        if centres is None:
            heavy, types_centres, pos_centres = config.getHeavy()
        else:
            pos_centres = centres[cidx]
        x = dcalc.evaluate(system=config,
            positions=pos_centres)
        if reduce_molecular is not None:
            x = reduce_molecular(x, axis=0)
        if norm_molecular:
            x = x/np.dot(x,x)**0.5
        X.append(x)
    t1 = time.time()
    if log:
        log << "[Finished in %fs]" % (t1-t0) << log.flush
    X = np.array(X)
    return X