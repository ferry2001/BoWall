-- BoWall local MySQL schema.
-- This file is idempotent: importing it again will not remove existing data.

CREATE TABLE IF NOT EXISTS `user` (
    `account` VARCHAR(36) NOT NULL,
    `phone` VARCHAR(32) NOT NULL,
    `name` VARCHAR(100) DEFAULT NULL,
    `password` VARCHAR(255) DEFAULT NULL,
    `status` TINYINT NOT NULL DEFAULT 1,
    `avatar` VARCHAR(512) DEFAULT NULL,
    `sign` VARCHAR(500) DEFAULT NULL,
    `address` VARCHAR(255) DEFAULT NULL,
    `country` VARCHAR(8) DEFAULT NULL,
    `native_language` VARCHAR(16) DEFAULT NULL,
    `english_level` DECIMAL(5,4) DEFAULT NULL,
    `update_time` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`account`),
    UNIQUE KEY `uk_user_phone` (`phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `posts` (
    `id` VARCHAR(36) NOT NULL,
    `account` VARCHAR(36) NOT NULL,
    `text` TEXT,
    `view_count` BIGINT NOT NULL DEFAULT 0,
    `like_count` BIGINT NOT NULL DEFAULT 0 COMMENT '点赞数冗余字段',
    `language` VARCHAR(16) NOT NULL DEFAULT 'unknown' COMMENT '正文主语言',
    `author_country` VARCHAR(8) DEFAULT NULL COMMENT '作者发帖时的国家快照',
    `is_featured` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为精品贴 (0:否, 1:是)',
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    KEY `idx_posts_account_date` (`account`, `update_date` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE `posts` ADD COLUMN `view_count` BIGINT NOT NULL DEFAULT 0;
ALTER TABLE `posts` ADD COLUMN `like_count` BIGINT NOT NULL DEFAULT 0 COMMENT '点赞数冗余字段';
ALTER TABLE `posts` ADD COLUMN `language` VARCHAR(16) NOT NULL DEFAULT 'unknown' COMMENT '正文主语言';
ALTER TABLE `posts` ADD COLUMN `author_country` VARCHAR(8) DEFAULT NULL COMMENT '作者发帖时的国家快照';
ALTER TABLE `posts` ADD COLUMN `is_featured` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为精品贴 (0:否, 1:是)';
ALTER TABLE `user` ADD COLUMN `country` VARCHAR(8) DEFAULT NULL;
ALTER TABLE `user` ADD COLUMN `native_language` VARCHAR(16) DEFAULT NULL;
ALTER TABLE `user` ADD COLUMN `english_level` DECIMAL(5,4) DEFAULT NULL;
CREATE INDEX `idx_posts_language` ON `posts` (`language`);

-- 既有账号按号码前缀回填国家；历史大陆手机号（11 位、1 开头）归为 CN。
UPDATE `user` SET `country` = CASE
    WHEN `phone` LIKE '+86%' OR `phone` LIKE '86%' OR `phone` LIKE '1__________' THEN 'CN'
    WHEN `phone` LIKE '+81%' OR `phone` LIKE '81%' THEN 'JP'
    WHEN `phone` LIKE '+82%' OR `phone` LIKE '82%' THEN 'KR'
    WHEN `phone` LIKE '+33%' OR `phone` LIKE '33%' THEN 'FR'
    WHEN `phone` LIKE '+49%' OR `phone` LIKE '49%' THEN 'DE'
    WHEN `phone` LIKE '+34%' OR `phone` LIKE '34%' THEN 'ES'
    WHEN `phone` LIKE '+7%' OR `phone` LIKE '7%' THEN 'RU'
    WHEN `phone` LIKE '+1%' THEN 'US' ELSE `country` END
WHERE `country` IS NULL OR `country` = '';
UPDATE `user` SET `native_language` = CASE `country`
    WHEN 'CN' THEN 'zh' WHEN 'JP' THEN 'ja' WHEN 'KR' THEN 'ko' WHEN 'FR' THEN 'fr'
    WHEN 'DE' THEN 'de' WHEN 'ES' THEN 'es' WHEN 'RU' THEN 'ru' ELSE 'en' END
WHERE `native_language` IS NULL OR `native_language` = '';
UPDATE `user` SET `english_level` = CASE WHEN `native_language` = 'en' THEN 1.0000 ELSE 0.1800 END
WHERE `english_level` IS NULL;

CREATE TABLE IF NOT EXISTS `post_dwell` (
    `id` VARCHAR(36) NOT NULL,
    `post_id` VARCHAR(36) NOT NULL,
    `account` VARCHAR(36) NOT NULL,
    `session_id` VARCHAR(64) NOT NULL,
    `dwell_seconds` BIGINT NOT NULL DEFAULT 0,
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_post_dwell_session` (`post_id`, `account`, `session_id`),
    KEY `idx_post_dwell_post` (`post_id`),
    KEY `idx_post_dwell_account` (`account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `comments` (
    `id` VARCHAR(36) NOT NULL,
    `posts_id` VARCHAR(36) NOT NULL,
    `account` VARCHAR(36) NOT NULL,
    `text` TEXT NOT NULL,
    `parent_id` VARCHAR(36) DEFAULT NULL,
    `reply_to_account` VARCHAR(36) DEFAULT NULL,
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `is_read` VARCHAR(3) NOT NULL DEFAULT 'no',
    `is_del` VARCHAR(3) NOT NULL DEFAULT 'no',
    PRIMARY KEY (`id`),
    KEY `idx_comments_posts` (`posts_id`),
    KEY `idx_comments_parent` (`parent_id`),
    KEY `idx_comments_account_read` (`account`, `is_read`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Existing installations can import these upgrades without losing comments.
ALTER TABLE `comments` ADD COLUMN `parent_id` VARCHAR(36) DEFAULT NULL;
ALTER TABLE `comments` ADD COLUMN `reply_to_account` VARCHAR(36) DEFAULT NULL;
ALTER TABLE `comments` ADD INDEX `idx_comments_parent` (`parent_id`);

CREATE TABLE IF NOT EXISTS `image` (
    `account` VARCHAR(36) NOT NULL,
    `url` VARCHAR(512) NOT NULL,
    `posts_id` VARCHAR(36) NOT NULL,
    `width` VARCHAR(16) DEFAULT NULL,
    `height` VARCHAR(16) DEFAULT NULL,
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `is_cover` VARCHAR(3) NOT NULL DEFAULT 'no',
    PRIMARY KEY (`posts_id`, `url`(191)),
    KEY `idx_image_account` (`account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `likes` (
    `id` VARCHAR(36) NOT NULL,
    `account` VARCHAR(36) NOT NULL,
    `post_id` VARCHAR(36) NOT NULL,
    `is_read` VARCHAR(3) NOT NULL DEFAULT 'no',
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_likes_account_post` (`account`, `post_id`),
    KEY `idx_likes_post` (`post_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE `likes` ADD COLUMN `is_read` VARCHAR(3) NOT NULL DEFAULT 'no';

-- 旧数据升级：仅回填未初始化的零值，后续由点赞接口原子维护。
UPDATE `posts` p SET p.`like_count` = (
    SELECT COUNT(*) FROM `likes` l WHERE l.`post_id` = p.`id`
) WHERE p.`like_count` = 0;

CREATE TABLE IF NOT EXISTS `message` (
    `id` VARCHAR(36) NOT NULL,
    `sender_account` VARCHAR(36) NOT NULL,
    `recipient_account` VARCHAR(36) NOT NULL,
    `content` TEXT NOT NULL,
    `is_read` VARCHAR(3) NOT NULL DEFAULT 'no',
    `is_del` VARCHAR(3) NOT NULL DEFAULT 'no',
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    KEY `idx_message_recipient_read` (`recipient_account`, `is_read`),
    KEY `idx_message_conversation` (`sender_account`, `recipient_account`, `update_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `notification` (
    `id` VARCHAR(36) NOT NULL,
    `account` VARCHAR(36) NOT NULL,
    `comments_id` VARCHAR(36) DEFAULT NULL,
    `message_id` VARCHAR(36) DEFAULT NULL,
    `status` VARCHAR(16) NOT NULL DEFAULT 'pending',
    `type` VARCHAR(16) NOT NULL,
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    KEY `idx_notification_account_status` (`account`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `followers` (
    `account` VARCHAR(36) NOT NULL,
    `followers_account` VARCHAR(36) NOT NULL,
    PRIMARY KEY (`account`, `followers_account`),
    KEY `idx_followers_target` (`followers_account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `fans` (
    `account` VARCHAR(36) NOT NULL,
    `fans_account` VARCHAR(36) NOT NULL,
    PRIMARY KEY (`account`, `fans_account`),
    KEY `idx_fans_account` (`fans_account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
