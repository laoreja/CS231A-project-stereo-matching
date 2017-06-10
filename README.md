# CS231A Course project

## Reimplementation-of-GC-Net

I mainly reimplement the GC-Net https://arxiv.org/pdf/1703.04309.pdf.

I implement two versions of the GC-Net model: one with a mask, the losses are masked, one without the mask.

## Results

### Qualitative results

The without-mask-version:
original image             |  prediction
:-------------------------:|:-------------------------:
![](https://raw.githubusercontent.com/laoreja/CS231A-project-stereo-matching/master/qualitative_results/SceneFlow_train_without_mask/gt_2.png)  |  ![](https://raw.githubusercontent.com/laoreja/CS231A-project-stereo-matching/master/qualitative_results/SceneFlow_train_without_mask/pre_2.png)
![](https://raw.githubusercontent.com/laoreja/CS231A-project-stereo-matching/master/qualitative_results/SceneFlow_train_without_mask/gt_4.png)  |  ![](https://raw.githubusercontent.com/laoreja/CS231A-project-stereo-matching/master/qualitative_results/SceneFlow_train_without_mask/pre_4.png)
