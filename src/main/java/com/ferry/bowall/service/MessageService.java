package com.ferry.bowall.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.spring.service.IService;
import com.ferry.bowall.entity.Message;

public interface MessageService extends IService<Message> {
    Long count(LambdaQueryWrapper<Message> messageLambdaQueryWrapper);
}
