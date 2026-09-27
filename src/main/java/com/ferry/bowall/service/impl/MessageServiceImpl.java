package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Message;
import com.ferry.bowall.mapper.MessageMapper;
import com.ferry.bowall.service.MessageService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class MessageServiceImpl extends ServiceImpl<MessageMapper, Message> implements MessageService {
    @Autowired
    private MessageMapper messageMapper;


    @Override
    public Long count(LambdaQueryWrapper<Message> messageLambdaQueryWrapper) {
        Long count = messageMapper.selectCount(messageLambdaQueryWrapper);
        return count;
    }
}
