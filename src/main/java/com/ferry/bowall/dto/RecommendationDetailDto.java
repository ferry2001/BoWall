package com.ferry.bowall.dto;

import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

/** 返回给调试/展示层的可解释推荐明细，所有组件均归一化到 0~1。 */
@Data
public class RecommendationDetailDto {
    private String mode;
    private Double totalScore;
    private Map<String, Double> components = new LinkedHashMap<>();
}
