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
    `update_time` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`account`),
    UNIQUE KEY `uk_user_phone` (`phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `posts` (
    `id` VARCHAR(36) NOT NULL,
    `account` VARCHAR(36) NOT NULL,
    `text` TEXT,
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    KEY `idx_posts_account_date` (`account`, `update_date` DESC)
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
    `update_date` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_likes_account_post` (`account`, `post_id`),
    KEY `idx_likes_post` (`post_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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
