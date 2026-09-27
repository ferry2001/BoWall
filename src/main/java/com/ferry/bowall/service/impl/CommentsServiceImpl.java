package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Comments;
import com.ferry.bowall.mapper.CommentsMapper;
import com.ferry.bowall.service.CommentsService;
import org.springframework.stereotype.Service;

@Service
public class CommentsServiceImpl extends ServiceImpl<CommentsMapper, Comments> implements CommentsService {

  
}
