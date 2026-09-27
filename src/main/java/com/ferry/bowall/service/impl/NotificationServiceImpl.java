package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Notification;
import com.ferry.bowall.mapper.NotificationMapper;
import com.ferry.bowall.service.NotificationService;
import org.springframework.stereotype.Service;

@Service
public class NotificationServiceImpl extends ServiceImpl<NotificationMapper, Notification> implements NotificationService {
}
