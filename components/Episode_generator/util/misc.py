import importlib

def instantiate_from_config(config):
    if config is None:
        return None
    if not "target" in config:
        raise KeyError("Expected key `target` to instantiate.")
    for k in config.keys():
        if k not in ['target', 'params']:
            print('warning: Unused key {} while instantiating {}'.format(k, config['target']))
    module, cls = config["target"].rsplit(".", 1)
    cls = getattr(importlib.import_module(module, package=None), cls)
    return cls(**config.get("params", dict()))