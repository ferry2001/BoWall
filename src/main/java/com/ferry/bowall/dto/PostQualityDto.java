package com.ferry.bowall.dto;

import lombok.Data;

/** 仅用于展示的帖子质量指标，不参与推荐排序。所有比率均为百分比（0-100）。 */
@Data
public class PostQualityDto {
    private String postId;
    private Long viewCount;
    private Long recordedSessionCount;
    private Long expectedDwellSeconds;
    private Long effectiveReadThresholdSeconds;
    private Long quickSkipThresholdSeconds;
    private Double effectiveReadRate;
    private Double quickSkipRate;
    private Double averageDwellSeconds;
    private Double medianDwellSeconds;
    private Double likeRate;
    private Double commentRate;
    private Double dwellScore;
}
