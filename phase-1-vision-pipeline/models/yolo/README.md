# YOLO weights go here

Copy your trained Ultralytics weights to:

    models/yolo/best.pt

That is the default path. Override it (highest precedence last):

1. config file:  `yolo: {weights_path: /somewhere/else.pt}`
2. environment:  `TOPOFORGE_YOLO_WEIGHTS=/somewhere/else.pt`
3. command line: `--weights /somewhere/else.pt`

The class names (router, switch, pc, ...) are read from the weights at load time and written to
`outputs/raw_yolo.json` under `producer.class_names`. Nothing in the pipeline hard-codes a class list.
