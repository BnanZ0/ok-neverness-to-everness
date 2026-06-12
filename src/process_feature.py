from ok.feature.Feature import Feature

from src import text_white_color
from src.Labels import Labels
from src.utils import game_filters as gf
from src.utils import image_utils as iu

SET_CHAR_LABELS = {Labels.char_1_text, Labels.char_2_text, Labels.char_3_text, Labels.char_4_text}


def process_feature(feature_name, feature: Feature):
    if feature_name in SET_CHAR_LABELS:
        feature.mat = iu.adjust_lightness_contrast_lab(feature.mat, brightness=0, contrast=100)
    match feature_name:
        case Labels.boss_lv_text:
            feature.mat = iu.binarize_bgr_by_brightness(feature.mat, threshold=180)
        case Labels.mini_map_arrow:
            feature.mat = iu.binarize_bgr_by_brightness(feature.mat, threshold=200)
        case Labels.is_current_char:
            feature.mat = gf.current_char_filter(feature.mat)
        case Labels.target:
            feature.mat = iu.binarize_bgr_by_brightness(feature.mat, threshold=245)
        case Labels.fish_start:
            feature.mat = iu.create_color_mask(feature.mat, text_white_color)
        case Labels.heist_lock_pick:
            feature.mat = iu.create_color_mask(feature.mat, text_white_color)
        case Labels.ult_ready:
            feature.mat = gf.ultimate_ready_filter(feature.mat)