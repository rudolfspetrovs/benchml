import numpy as np
from ..transforms import *

def compile_physchem_class(custom_fields=[], with_hyper=False, **kwargs):
    models = []
    for descriptor_set in ["basic", "core", "logp", "extended"]:
        models.extend([
            Module(
                tag="bmol_physchem_%s_rf_class" % descriptor_set,
                transforms=[
                    ExtXyzInput(tag="input"),
                    Physchem2D(tag="Physchem2D",
                        args={"select_predef": descriptor_set},
                        inputs={"configs": "input.configs"}),
                    PhyschemUser(tag="PhyschemUser",
                        args={
                            "fields": custom_fields
                        },
                        inputs={"configs": "input.configs"}),
                    Concatenate(tag="descriptor",
                        inputs={"X": [ "Physchem2D.X", "PhyschemUser.X" ]}),
                    DoDivideBySize(
                        tag="input_norm",
                        args={
                            "config_to_size": "lambda c: len(c)",
                            "skip_if_not_force": True,
                            "force": None
                        },
                        inputs={
                            "configs": "input.configs",
                            "meta": "input.meta",
                            "y": "input.y"
                        }),
                    RandomForestClassifier(tag="predictor",
                        inputs={"X": "descriptor.X", "y": "input.y"}),
                    UndoDivideBySize(
                        tag="output",
                        inputs={"y": "predictor.y", "sizes": "input_norm.sizes"}) 
                ],
                hyper=GridHyper(
                    Hyper({ "input_norm.force": [False, True] }),
                    Hyper({"predictor.max_depth": [None]})),
                broadcast={"meta": "input.meta"},
                outputs={"y": "output.z"}),
        ])
    return models

def compile_ecfp_class():
    return [
        Module(
            tag="bmol_ecfp_svm_class",
            transforms=[
                ExtXyzInput(tag="input"),
                MorganFP(
                    tag="descriptor",
                    args={"length": 4096, "radius": 2, "normalize": True},
                    inputs={"configs": "input.configs"}),
                KernelDot(
                    tag="kernel",
                    inputs={"X": "descriptor.X"}),
                SupportVectorClassifier(
                    tag="predictor",
                    args={
                        "C": None,
                        "power": 2
                    },
                    inputs={
                        "K": "kernel.K",
                        "y": "input.y"
                    }),
            ],
            hyper=GridHyper(
                Hyper({ "predictor.C": np.logspace(-9,+7, 17), }),
                Hyper({ "predictor.power": [ 2. ] })),
            broadcast={ "meta": "input.meta" },
            outputs={ "y": "predictor.z" }
        ),
    ]
def register_all():
    return {
        "bmol_physchem_class": compile_physchem_class,
        "bmol_ecfp_class": compile_ecfp_class
    }
