---
license: apache-2.0
tags:
- vlx
- object-detection
- grounding
- multimodal
- REC
- VLM
- zero-shot-object-detection
language:
- zh
- en
pipeline_tag: image-text-to-text
library_name: transformers
---

# VLX-Seek-1.5-10B

VLX-Seek-1.5-10B is the open-source 10B model in the VLX-Seek 1.5 family, designed for fine-grained perception and visual grounding in embodied scenarios. It targets practical settings such as drones, robots, robotic dogs, surveillance cameras, inspection systems, and other edge-side visual intelligence applications where a model must identify what is present, localize the right instance, and avoid grounding objects that are absent.

Unlike coordinate-generation-based VLMs that directly decode bounding-box numbers, VLX-Seek reformulates localization as region retrieval and region reference. Candidate visual regions are represented as addressable entities, and the model answers by selecting, comparing, and referring to those regions. This makes localization more aligned with the strengths of language models: comparison, selection, reference, and reasoning.

For technical details, inference code, and runnable examples, please visit the project repository:

**GitHub: [om-ai-lab/VLX-Seek](https://github.com/om-ai-lab/VLX-Seek)**

## Model Highlights

- **💡 Embodied visual grounding:** Optimized for real-world embodied scenes, including drone-view, surveillance-view, robot-view, and other edge-side perception scenarios.
- **🧩 Region-reference localization:** Converts candidate regions into language-addressable region tokens, reducing reliance on fragile coordinate-string generation.
- **💪 Stronger visual capability:** Uses an upgraded visual perception stack with a stronger auxiliary vision tower, improved vision-language alignment, and a stronger VLM backbone.
- **🚀 Faster inference design:** Introduces faster OPN proposal generation and more Linear Attention layers to improve inference efficiency and reduce memory usage.
- **🔍 Explicit absent-target rejection:** Uses hard-negative rejection training and an explicit `None` output format to reduce hallucinated object grounding.
- **📦 Multi-scale family:** VLX-Seek 1.5 is planned in 0.6B, 3B, and 10B sizes. This model card describes the 10B checkpoint.

## Intended Use

VLX-Seek-1.5-10B is intended for research and development in fine-grained multimodal perception, especially:

- Open-vocabulary object detection and localization.
- Referring expression comprehension.
- Multi-object visual grounding.
- Object counting with region-level evidence.
- Drone-view perception with small objects and dense layouts.
- Robot-centric and embodied spatial reasoning.
- Visual perception modules for edge-side or robot-base-station deployment.
- Experiments that require explicit rejection of absent targets.

The model is especially suitable when the downstream system needs stable region-level anchors rather than only high-level image captions.

## How to Use

VLX-Seek uses a custom region-reference inference pipeline, including candidate-region proposal generation, region-token construction, prompt formatting, and output post-processing. We provide the full inference code and detailed runnable examples in the official repository:

[https://github.com/om-ai-lab/VLX-Seek](https://github.com/om-ai-lab/VLX-Seek)

Please follow the repository instructions for installation, model loading, inference scripts, prompt templates, and visualization examples.


## Evaluation

### General Recognition

<p align="left">
  <img src="https://om-ai-lab.github.io/images/vlx-seek1.5/Table1_new.jpg" alt="Table 1: Results on common object detection benchmarks." width="70%">
</p>

<p align="left">
  <img src="https://om-ai-lab.github.io/images/vlx-seek1.5/Table2_new.jpg" alt="Table 2: Results on referring expression comprehension benchmarks." width="70%">
</p>

<p align="left">
  <img src="https://om-ai-lab.github.io/images/vlx-seek1.5/Table3_new.jpg" alt="Table 3: Results on REC and counting benchmarks." width="70%">
</p>

### Drone Scenarios

<p align="left">
  <img src="https://om-ai-lab.github.io/images/vlx-seek1.5/Table4_new.jpg" alt="Table 4: Results on drone-view benchmarks." width="70%">
</p>

### Embodied Robot Scenarios

<p align="left">
  <img src="https://om-ai-lab.github.io/images/vlx-seek1.5/Table5_new.jpg" alt="Table 5: Results on embodied spatial reasoning benchmarks." width="70%">
</p>

### Object Hallucination Evaluation

<p align="left">
  <img src="https://om-ai-lab.github.io/images/vlx-seek1.5/Table6_new.jpg" alt="Table 6: Object hallucination comparison on HumanRef, VisDrone, and RefDrone." width="70%">
</p>

For full comparison tables and qualitative examples, see the VLX-Seek 1.5 blog:

[VLX-Seek 1.5: Enhanced Fine-grained Perception for Embodied Scenarios](https://om-ai-lab.github.io/2026_07_06_vlx_seek_1_5_en.html)

## Limitations

- VLX-Seek relies on candidate regions. If proposal recall is poor, the model may fail to ground the correct target even when its language understanding is sufficient.
- Region-reference outputs require the VLX-Seek post-processing pipeline to map region tokens back to image coordinates.
- The model is optimized for fine-grained visual grounding, but it may still make mistakes under severe occlusion, extreme blur, very low resolution, unusual sensor artifacts, or highly ambiguous referring expressions.
- Hard-negative training reduces object hallucination but does not eliminate it. Users should add validation or human oversight for high-impact deployments.


## Ethical Considerations

VLX-Seek-1.5-10B can be used in embodied and monitoring scenarios, including cameras, drones, and robots. Such applications may involve privacy, safety, and fairness risks. Users are responsible for complying with applicable laws and institutional policies, obtaining appropriate consent where needed, and avoiding deployments that enable unlawful surveillance, discrimination, or unsafe autonomous actions.

## Citation

If you use VLX-Seek-1.5-10B, please cite the project:

```bibtex
@misc{vlxseek15_2026,
  title = {VLX-Seek 1.5: Enhanced Fine-grained Perception for Embodied Scenarios},
  author = {Om AI Lab},
  year = {2026},
  url = {https://om-ai-lab.github.io/2026_07_06_vlx_seek_1_5_en.html}
}
```

## Contact

For technical details, inference examples, and updates, please use the official project repository:

[om-ai-lab/VLX-Seek](https://github.com/om-ai-lab/VLX-Seek)
