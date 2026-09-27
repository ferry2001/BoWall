package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Fans;
import com.ferry.bowall.entity.Followers;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.mapper.FansMapper;
import com.ferry.bowall.mapper.FollowersMapper;
import com.ferry.bowall.mapper.UserMapper;
import com.ferry.bowall.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {
    @Autowired
    private UserMapper userMapper;

    @Autowired
    private FansMapper fansMapper;

    @Autowired
    private FollowersMapper followersMapper;

    @Override
    public List<User> getUserList() {
        return userMapper.getUserList();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateUser(User user) {
        userMapper.updateUser(user);
    }

    @Override
    public List<User> friends(String account) {
        return userMapper.friends(account);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void addFanAndFollowUser(String account, String fansAccount) {

        fansMapper.save(account, fansAccount);
        followersMapper.save(fansAccount, account);
    }

    @Override
    public void deleteFanAndFollowUser(String account, String fansAccount) {
        LambdaQueryWrapper<Fans> fansLambdaQueryWrapper = new LambdaQueryWrapper<>();
        fansLambdaQueryWrapper.eq(Fans::getAccount, account);
        fansLambdaQueryWrapper.eq(Fans::getFansAccount, fansAccount);
        LambdaQueryWrapper<Followers> followersLambdaQueryWrapper = new LambdaQueryWrapper<>();
        followersLambdaQueryWrapper.eq(Followers::getAccount, fansAccount);
        followersLambdaQueryWrapper.eq(Followers::getFollowersAccount, account);

        fansMapper.delete(fansLambdaQueryWrapper);
        followersMapper.delete(followersLambdaQueryWrapper);
    }

    @Override
    public User getUser(String account) {
        return userMapper.getUser(account);
    }

    @Override
    public String getUserName(String account) {
        return userMapper.getUserName(account);
    }

    @Override
    public String getUserAvatar(String account) {
        return userMapper.getAvatar(account);
    }

    @Override
    public List<User> getUsers(Set<String> accounts) {
        return userMapper.getUsers(accounts);
    }

}
