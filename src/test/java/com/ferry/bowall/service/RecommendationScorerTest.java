package com.ferry.bowall.service;

import com.ferry.bowall.config.RecommendationProperties;
import com.ferry.bowall.dto.PostQualityDto;
import com.ferry.bowall.entity.Posts;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RecommendationScorerTest {
    private final RecommendationScorer scorer = new RecommendationScorer(new RecommendationProperties());

    @Test
    void highQualityPostScoresHigherThanQuickSkipPost() {
        Posts post = new Posts();
        post.setId("quality-post");
        post.setUpdateDate(LocalDateTime.now().minusHours(2));

        PostQualityDto high = quality(120, 88, 76, 8, 12, 4);
        PostQualityDto low = quality(120, 12, 8, 70, 1, 0);

        double highScore = scorer.score(post, high, 6, 20, 50, 3, "zh", .2, "zh").getTotalScore();
        double lowScore = scorer.score(post, low, 0, 0, 50, 3, "zh", .2, "zh").getTotalScore();

        assertTrue(highScore > lowScore);
        assertTrue(scorer.score(post, high, 6, 20, 50, 3, "zh", .2, "zh").getComponents().containsKey("languageMatch"));
    }

    @Test
    void supportsFastTimeOrderFallback() {
        assertTrue(scorer.useTimeMode("time"));
        assertFalse(scorer.useTimeMode("quality"));
    }

    @Test
    void audienceAndHeatProvideBoundedGlobalDistributionBoost() {
        Posts post = new Posts();
        post.setId("audience-post");
        post.setUpdateDate(LocalDateTime.now().minusHours(2));
        PostQualityDto quality = quality(100, 50, 45, 25, 4, 1);

        double unknownAuthor = scorer.score(post, quality, 0, 0, 50, 3, "zh", .2, "zh").getTotalScore();
        double establishedAuthor = scorer.score(post, quality, 0, 100, 50, 3, "zh", .2, "zh").getTotalScore();

        assertTrue(establishedAuthor > unknownAuthor);
        assertTrue(establishedAuthor <= 100);
    }

    @Test
    void nativeLanguageOutranksUnreadableForeignLanguage() {
        Posts post = new Posts();
        post.setId("language-post");
        post.setUpdateDate(LocalDateTime.now().minusHours(1));
        PostQualityDto quality = quality(80, 70, 60, 15, 8, 2);

        double chinese = scorer.score(post, quality, 0, 0, 50, 3, "zh", .18, "zh").getTotalScore();
        double french = scorer.score(post, quality, 0, 0, 50, 3, "zh", .18, "fr").getTotalScore();

        assertTrue(chinese > french);
    }

    private PostQualityDto quality(long views, double dwellScore, double effectiveRate,
                                   double skipRate, double likeRate, double commentRate) {
        PostQualityDto dto = new PostQualityDto();
        dto.setViewCount(views);
        dto.setDwellScore(dwellScore);
        dto.setEffectiveReadRate(effectiveRate);
        dto.setQuickSkipRate(skipRate);
        dto.setLikeRate(likeRate);
        dto.setCommentRate(commentRate);
        return dto;
    }
}
