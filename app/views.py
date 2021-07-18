from django.shortcuts import render, redirect
from app.models import NaturalPerson, Position, Organization, Activity, TransferRecord, Paticipant
from django.contrib import auth, messages
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from app.forms import UserForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from app.data_import import load
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q
from app.utils import MyMD5PasswordHasher, MySHA256Hasher, load_local_json
import app.utils as utils
from django.conf import settings
from django.urls import reverse
import json
from datetime import datetime
from time import mktime

from django.views.decorators.http import require_POST, require_GET
from django.db import transaction
import re

local_dict = load_local_json()
underground_url = local_dict['url']['base_url']
# underground_url = 'http://127.0.0.1:8080/appointment/index'
hash_coder = MySHA256Hasher(local_dict['hash']['base_hasher'])


def index(request):
    arg_origin = request.GET.get('origin')
    modpw_status = request.GET.get('success')
    # request.GET['success'] = "no"
    arg_islogout = request.GET.get('is_logout')
    if arg_islogout is not None:
        if request.user.is_authenticated:
            auth.logout(request)
            return render(request, 'index.html', locals())
    if arg_origin is None:  # 非外部接入
        if request.user.is_authenticated:
            return redirect('/welcome/')
            '''
            valid, user_type , html_display = utils.check_user_type(request)
            if not valid:
                return render(request, 'index.html', locals())
            return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
            '''
    if request.method == 'POST' and request.POST:
        username = request.POST['username']
        password = request.POST['password']

        try:
            user = User.objects.get(username=username)
        except:
            # if arg_origin is not None:
            #    redirect(f'/login/?origin={arg_origin}')
            message = local_dict['msg']['404']
            invalid = True
            return render(request, 'index.html', locals())
        userinfo = auth.authenticate(username=username, password=password)
        if userinfo:
            auth.login(request, userinfo)
            request.session['username'] = username
            if arg_origin is not None:
                # 加时间戳
                # 以及可以判断一下 arg_origin 在哪
                # 看看是不是 '/' 开头就行
                d = datetime.utcnow()
                t = time.mktime(datetime.timetuple(d))
                timeStamp = str(int(t))
                print("utc time: ", d)
                print(timeStamp)
                en_pw = hash_coder.encode(username + timeStamp)
                try:
                    userinfo = NaturalPerson.objects.get(pid=username)
                    name = userinfo.pname
                    return redirect(arg_origin + f'?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}&name={name}')
                except:
                    return redirect(arg_origin + f'?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}')
            else:
                return redirect('/welcome/')
                '''
                valid, user_type , html_display = utils.check_user_type(request)
                if not valid:
                    return render(request, 'index.html', locals())
                return redirect('/stuinfo') if user_type == "Person" else redirect('/orginfo')
                '''
        else:
            invalid = True
            message = local_dict['msg']['406']

    # 非 post 过来的
    if arg_origin is not None:
        if request.user.is_authenticated:
            d = datetime.utcnow()
            t = time.mktime(datetime.timetuple(d))
            timeStamp = str(int(t))
            print("utc time: ", d)
            print(timeStamp)
            username = request.session['username']
            en_pw = hash_coder.encode(username + timeStamp)
            return redirect(arg_origin + f'?Sid={username}&timeStamp={timeStamp}&Secret={en_pw}')

    return render(request, 'index.html', locals())


# Return content
# Sname 姓名 Succeed 成功与否
wechat_login_coder = MyMD5PasswordHasher("wechat_login")


def miniLogin(request):
    try:
        assert (request.method == 'POST')
        username = request.POST['username']
        password = request.POST['password']
        secret_token = request.POST['secret_token']
        assert (wechat_login_coder.verify(username, secret_token) == True)
        user = User.objects.get(username=username)

        userinfo = auth.authenticate(username=username, password=password)

        if userinfo:

            auth.login(request, userinfo)

            request.session['username'] = username
            en_pw = hash_coder.encode(request.session['username'])
            user_account = NaturalPerson.objects.get(pid=username)
            return JsonResponse(
                {'Sname': user_account.pname, 'Succeed': 1},
                status=200
            )
        else:
            return JsonResponse(
                {'Sname': username, 'Succeed': 0},
                status=400
            )
    except:
        return JsonResponse(
            {'Sname': '', 'Succeed': 0},
            status=400
        )


@login_required(redirect_field_name='origin')
def stuinfo(request, name = None):
    '''
        进入到这里的逻辑:
        首先必须登录，并且不是超级账户
        如果name是空
            如果是个人账户，那么就自动跳转个人主页"/stuinfo/myname"
            如果是组织账户，那么自动跳转welcome
        如果name非空但是找不到对应的对象
            自动跳转到welcome
        如果name有明确的对象
            如果不重名
                如果是自己，那么呈现并且有左边栏
                如果不是自己或者自己是组织，那么呈现并且没有侧边栏
            如果重名
                那么期望有一个"+"在name中，如果搜不到就跳转到Search/？Query=name让他跳转去
    '''
    
    try:
        user = request.user
        valid, user_type, html_display = utils.check_user_type(request)
        if not valid:
            return redirect('/logout/')

        if name is None:
            if user_type == 'Organization':
                return redirect('/welcome/')
            else:
                assert(user_type == 'Person')
                try:
                    oneself = NaturalPerson.objects.activated().get(pid=user)
                except:
                    return redirect('/welcome/')
                return redirect('/stuinfo/' + oneself.pname)
        else:
            # 先对可能的加号做处理
            name_list = name.split("+")
            name = name_list[0]
            person = NaturalPerson.objects.activated().filter(pname=name)
            if len(person) == 0:            # 查无此人
                return redirect('/welcome/')
            if len(person) == 1:        # 无重名
                person = person[0]
            else:                       # 有很多人，这时候假设加号后面的是user的id
                if len(name_list) == 1: # 没有任何后缀信息，那么如果是自己则跳转主页，否则跳转搜索
                    if user_type == 'Person' and NaturalPerson.objects.activated().get(pid=user).pname == name:
                        person = NaturalPerson.objects.activated().get(pid=user)
                    else:               # 不是自己，信息不全跳转搜索
                        return redirect('/search?Query=' + name)        
                else:
                    obtain_id = int(name_list[1])                       # 获取增补信息
                    get_user = User.objects.get(id=obtain_id)
                    potential_person = NaturalPerson.objects.activated().get(pid=get_user)
                    assert potential_person in person
                    person = potential_person

            modpw_status = request.GET.get('modinfo', None)

            is_myself = user_type == 'Person' and person.pid == user    # 用一个字段储存是否是自己
            is_first = person.firstTimeLogin                            # 是否为第一次登陆
            if is_myself and is_first:
                return redirect('/modpw/')

            # 处理组织相关的信息
            join_pos_id_list = Position.objects.activated().filter(person=person)
            control_pos_id_list = join_pos_id_list.filter(pos=0)        # 最高级, 是非密码管理员

            html_display['modpw_code'] = modpw_status is not None and modpw_status == 'success'
            html_display['underground_url'] = underground_url                       # 跳转至地下室预约系统的
            html_display['warn_code'] = request.GET.get('warn_code', 0)             # 是否有来自外部的消息
            html_display['warn_message'] = request.GET.get('warn_message', "")      # 提醒的具体内容 
            html_display['userinfo'] = person
            html_display['is_myself'] = is_myself
            html_display['join_org_list'] = Organization.objects.filter(org__in = join_pos_id_list.values('org'))               # 我属于的组织
            html_display['control_org_list'] = list(Organization.objects.filter(org__in = control_pos_id_list.values('org')))   # 我管理的组织
            html_display['title_name'] = 'User Profile'
            html_display['narbar_name'] = '个人主页'
            
            return render(request, 'stuinfo.html', locals())
    except:
        auth.logout(request)
        return redirect('/index/')



@login_required(redirect_field_name='origin')
def request_login_org(request, name=None):  # 特指个人希望通过个人账户登入组织账户的逻辑
    '''
        这个函数的逻辑是，个人账户点击左侧的管理组织直接跳转登录到组织账户
        首先检查登录的user是个人账户，否则直接跳转orginfo
        如果个人账户对应的是name对应的组织的最高权限人，那么允许登录，否则跳转回stuinfo并warning
    '''
    user = request.user
    valid, u_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect('/logout/')
    if u_type == "Organization":
        return redirect('/orginfo/')
    try:
        me = NaturalPerson.objects.activated().get(pid=user)
    except:  # 找不到合法的用户
        return redirect('/welcome/')
    if name is None:  # 个人登录未指定登入组织,属于不合法行为,弹回欢迎
        return redirect('/welcome/')
    else:   # 确认有无这个组织
        try:
            org = Organization.objects.get(oname=name)
        except:  # 找不到对应组织
            urls = '/stuinfo/'+me.pname+"?warn_code=1&warn_message=找不到对应组织,请联系管理员!"
            return redirect(urls)
        try:
            position = Position.objects.activated().filter(org=org, person=me)
            assert len(position) == 1
            position = position[0]
            assert position.pos == 0
        except:
            urls = '/stuinfo/'+me.pname+"?warn_code=1&warn_message=没有登录到该组织账户的权限!"
            return redirect(urls)
        # 到这里,是本人组织并且有权限登录
        auth.logout(request)
        auth.login(request, org.oid)  # 切换到组织账号
        return redirect('/orginfo/')


@login_required(redirect_field_name='origin')
def orginfo(request, name=None):  # 此时的登录人有可能是负责人,因此要特殊处理
    '''
        orginfo负责呈现组织主页，逻辑和stuinfo是一样的，可以参考
    '''
    user = request.user
    valid, u_type, html_display = utils.check_user_type(request)
    me = NaturalPerson.objects.activated().get(pid = user) if u_type == 'Person' else Organization.objects.get(oid=user)
    if not valid:
        return redirect('/logout/')
    if name is None:
        if u_type == 'Person':
            return redirect('/welcome/')
        try:
            org = Organization.objects.activated().get(oid=user)
        except:
            return redirect('/welcome/')
        return redirect('/orginfo/' + org.oname)
    try:
        org = Organization.objects.activated().get(oname=name)
    except:
        return redirect('/welcome/')


    # 补充一些呈现信息
    html_display['title_name'] = 'Org. Profile'
    html_display['narbar_name'] = '组织主页'
    html_display['avatar_path'] = utils.get_user_ava(me)
    return render(request, 'orginfo.html', locals())


@login_required(redirect_field_name='origin')
def homepage(request):
    
    valid, u_type, html_display = utils.check_user_type(request) #
    is_person = True if u_type == 'Person' else False #
    if not valid:
        return redirect('/logout/') #
    me = NaturalPerson.objects.get(
        pid=request.user) if is_person else Organization.objects.get(oid=request.user) #
    myname = me.pname if is_person else me.oname #
    # 直接储存在html_display中
    #profile_name = "个人主页" if is_person else "组织主页"
    #profile_url = "/stuinfo/" + myname if is_person else "/orginfo/" + myname

    # 补充一些呈现信息
    html_display['title_name'] = 'Welcome Page'
    html_display['narbar_name'] = '近期要闻' #
    html_display['avatar_path'] = utils.get_user_ava(me)
    return render(request, 'welcome_page.html', locals())


@login_required(redirect_field_name='origin')
def account_setting(request):
    valid, user_type, html_display = utils.check_user_type(request)
    if not valid:
        return redirect('/logout/')
    undergroundurl = underground_url

    user = request.user
    info = NaturalPerson.objects.filter(pid=user)
    userinfo = info.values()[0]

    useroj = NaturalPerson.objects.get(pid=user)

    former_img = html_display['avatar_path']

    if request.method == 'POST' and request.POST:
        aboutbio = request.POST['aboutBio']
        tel = request.POST['tel']
        email = request.POST['email']
        Major = request.POST['major']
        ava = request.FILES.get('avatar')
        expr = bool(tel or Major or email or aboutbio or ava)
        if aboutbio != '':
            useroj.pBio = aboutbio
        if Major != '':
            useroj.pmajor = Major
        if email != '':
            useroj.pemail = email
        if tel != '':
            useroj.ptel = tel
        if ava is None:
            pass
        else:
            useroj.avatar = ava
        useroj.save()
        avatar_path = settings.MEDIA_URL + str(ava)
        if expr == False:
            return render(request, 'user_account_setting.html', locals())

        else:
            upload_state = True
            return redirect("/stuinfo/?modinfo=success")
    return render(request, 'user_account_setting.html', locals())


def register(request):
    if request.user.is_superuser:
        if request.method == 'POST' and request.POST:
            name = request.POST['name']
            password = request.POST['password']
            sno = request.POST['snum']
            email = request.POST['email']
            password2 = request.POST['password2']
            pyear = request.POST['syear']
            #pgender = request.POST['sgender']
            if password != password2:
                render(request, 'index.html')
            else:
                # user with same sno
                same_user = NaturalPerson.objects.filter(pid=sno)
                if same_user:
                    render(request, 'auth_register_boxed.html')
                same_email = NaturalPerson.objects.filter(pemail=email)
                if same_email:
                    render(request, 'auth_register_boxed.html')

                # OK!
                user = User.objects.create(username=sno)
                user.set_password(password)
                user.save()

                new_user = NaturalPerson.objects.create(pid=user)
                new_user.pname = name
                new_user.pemail = email
                new_user.pyear = pyear
                new_user.save()
                return HttpResponseRedirect('/index/')
        return render(request, 'auth_register_boxed.html')
    else:
        return HttpResponseRedirect('/index/')


# @login_required(redirect_field_name=None)
def logout(request):
    auth.logout(request)
    return HttpResponseRedirect('/index/')


'''
def org_spec(request, *args, **kwargs):
    arg = args[0]
    org_dict = local_dict['org']
    title = org_dict[arg]
    org = Organization.objects.filter(oname=title)
    pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
    try:
        pos = Position.objects.filter(Q(org=org) | Q(pos='部长') | Q(pos='老板'))
        boss_no = pos.values()[0]['person_id']#存疑，可能还有bug here
        boss = NaturalPerson.objects.get(pid=boss_no).pname
        job = pos.values()[0]['pos']
    except:
        person_incharge = '负责人'
    return render(request, 'org_spec.html', locals())
'''


def get_stu_img(request):
    print("in get stu img")
    stuId = request.GET.get('stuId')
    if stuId is not None:
        try:
            print(stuId)
            img_path = NaturalPerson.objects.get(pid=stuId).avatar
            if str(img_path) == '':
                img_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
            else:
                img_path = settings.MEDIA_URL + str(img_path)
            print(img_path)
            return JsonResponse({'path': img_path}, status=200)
        except:
            return JsonResponse({'message': "Image not found!"}, status=404)
    return JsonResponse({'message': 'User not found!'}, status=404)


def search(request):
    '''
        搜索界面的呈现逻辑
        分成搜索个人和搜索组织两个模块，每个模块的呈现独立开，有内容才呈现，否则不显示
        搜索个人：
            支持使用姓名搜索，支持对未设为不可见的昵称和专业搜索
            搜索结果的呈现采用内容/未公开表示，所有列表为people_filed
        搜索组织
            支持使用组织名、组织类型搜索、一级负责人姓名
            组织的呈现内容由拓展表体现，不在这个界面呈现具体成员

    '''
    try:
        valid, user_type, html_display = utils.check_user_type(request)
        if not valid:
            return redirect('/logout/')
  
        undergroundurl = underground_url
        query = request.GET.get('Query', '')
        if query == '':
            return redirect('/welcome/')

        # 首先搜索个人
        people_list = NaturalPerson.objects.filter(
            Q(pname__icontains=query) | (Q(pnickname__icontains=query)) | (Q(pmajor__icontains = query)))

        # 接下来准备呈现的内容

        # 首先是准备搜索个人信息的部分
        people_field = ['姓名', '年级&班级', '昵称', '性别', '专业', '邮箱', '电话', '宿舍', '状态']

        return render(request, 'search.html', locals())
    except:
        auth.logout(request)
        return redirect('/index/')




def test(request):
    request.session['cookies'] = 'hello, i m still here.'
    return render(request, 'all_org.html')


@login_required(redirect_field_name='origin')
def modpw(request):
    err_code = 0
    err_message = None
    username = request.session['username']  # added by wxy
    user = User.objects.get(username=username)
    useroj = NaturalPerson.objects.get(pid=user)
    isFirst = useroj.firstTimeLogin
    if str(useroj.avatar) == '':
        avatar_path = settings.MEDIA_URL + 'avatar/codecat.jpg'
    else:
        avatar_path = settings.MEDIA_URL + str(useroj.avatar)
    if request.method == 'POST' and request.POST:
        oldpassword = request.POST['pw']
        newpw = request.POST['new']
        username = request.session['username']
        strict_check = False

        if oldpassword == newpw and strict_check:
            err_code = 1
            err_message = "新密码不能与原密码相同"
        elif newpw == username and strict_check:
            err_code = 2
            err_message = "新密码不能与学号相同"
        else:
            userauth = auth.authenticate(
                username=username, password=oldpassword)
            if userauth:
                user = User.objects.get(username=username)
                if user:
                    user.set_password(newpw)
                    user.save()
                    stu = NaturalPerson.objects.filter(pid=user)
                    stu.update(firstTimeLogin=False)

                    urls = reverse("index") + "?success=yes"
                    return redirect(urls)
                else:
                    err_code = 3
                    err_message = "学号不存在"
            else:
                err_code = 4
                err_message = "原始密码不正确"
    return render(request, 'modpw.html', locals())


def load_data(request):
    if request.user.is_superuser:
        df_1819 = load()
        for i in range(len(df_1819)):  # import 2018 stu info.
            username = str(df_1819['学号'].iloc[i])
            sno = username
            password = sno
            email = df_1819['邮箱'].iloc[i]
            if email == 'None':
                if sno[0] == '2':
                    email = sno + '@stu.pku.edu.cn'
                else:
                    email = sno + '@pku.edu.cn'
            tel = str(df_1819['手机号'].iloc[i])
            year = '20' + sno[0:2]
            gender = df_1819['性别'].iloc[i]
            major = df_1819['专业'].iloc[i]
            name = df_1819['姓名'].iloc[i]
            pclass = df_1819['班级'].iloc[i]
            user = User.objects.create(username=username)
            user.set_password(password)
            user.save()
            stu = NaturalPerson.objects.create(pid=sno)
            stu.pemail = email
            stu.ptel = tel
            stu.pyear = year
            stu.pgender = gender
            stu.pmajor = major
            stu.pname = name
            stu.pclass = pclass
            stu.save()
        return render(request, 'debugging.html')




# 参与活动，get 传两个简单参数即可，活动 aid，价格等级
# 再加一个 origin from，点一下即可返回 ( 可以看到已经报名 )
# 活动的多字段怎么弄
@require_GET
@login_required(redirect_field_name='origin')
def engage_activity(request):
    origin = request.GET.get('origin')
    if origin is None:
        origin = '/'
    context = dict()
    context['origin'] = origin
    choice = request.GET.get('choice')
    # 默认是 0，没有分级的情况下可以只传 aid
    if choice is None:
        choice = 0
    else:
        choice = int(choice)
    aid = request.GET.get('aid')
    pid = request.session['username']

    try:
        activity = Activity.objects.select_for_update().filter(id=aid)
        payer = NaturalPerson.objects.select_for_update().filter(pid__username=pid)
        with transaction.atomic():
            assert(len(activity) == 1)
            assert(len(payer) == 1)
            activity = activity[0]
            payer = payer[0]

            try:
                panticipant = Paticipant.objects.get(aid=activity, pid=payer)
                context['msg'] = 'You have already participated in the activity. If you are not deliberately do it, please contact the administrator to report this bug.'
                return render(request, 'msg.html', context)
            except:
                pass

            oid = activity.oid_id
            orgnization = Organization.objects.select_for_update().filter(oid=oid)
            assert(len(orgnization) == 1)
            orgnization = orgnization[0]

            amount = float(activity.YQPoint[choice])
            cnt = activity.Places[choice]
            if cnt  <= 0:
                context['msg'] = 'Failed to fetch the ticket.'
                return render(request, 'msg.html', context)
            if payer.YQPoint < amount:
                context['msg'] = 'No enough YQPoint'
                return render(request, 'msg.html', context)
            payer.YQPoint -= float(amount)
            activity.Places[choice] = cnt - 1
            orgnization.YQPoint += float(amount)

            record = TransferRecord.objects.create(proposer=request.user, recipient=orgnization.oid)
            record.amount = amount
            record.message = f'Participate Activity {activity.aname}'
            record.tstatus = 0 # Wating
            record.time = str(datetime.now())

            panticipant = Paticipant.objects.create(aid=activity, pid=payer)

            panticipant.save()
            record.save()
            payer.save()
            activity.save()
            orgnization.save()



    except:
        context['msg'] = 'Unexpected failure. If you are not deliberately do it, please contact the administrator to report this bug.'
        return render(request, 'msg.html', context)



    context['msg'] = 'Successfully participate the activity.'
    return render(request, 'msg.html', context)




# 用已有的搜索，加一个转账的想他转账的 field
# 调用的时候传一下 url 到 origin
# 搜索不希望出现学号，rid 为 User 的 index
@require_GET
@login_required(redirect_field_name='origin')
def transaction_page(request):
    recipient_id = request.GET.get('rid')
    origin = request.GET.get('origin')
    if origin is None:
        origin = '/'
    # 可以有一个默认金额，但好像用不到
    # amount = request.GET.get('amount')
    context = dict()

    # r_user = User.objects.get(id=recipient_id)

    try:
        if re.match('zz\d+', recipient_id) is not None:
            recipient = Organization.objects.get(oid=recipient_id)
            recipient_type = 'org'
        else:
            recipient = NaturalPerson.objects.get(pid=recipient_id)
            recipient_type = 'np'
    except:
        context['msg'] = 'Unexpected recipient. If you are not deliberately doing this, please contact the administrator to report this bug.'
        context['origin'] = origin
        return render(request, 'msg.html', context)

    if recipient_type == 'np':
        name = recipient.pnickname
        if name == '':
            name = recipient.pname
        context['avatar'] = recipient.avatar
    else:
        name = recipient.oname
    context['name'] = name
    context['rid'] = recipient_id 
    context['rtype'] = recipient_type
    context['origin'] = origin
    return render(request, 'transaction_page.html', context)



# 涉及表单，一般就用 post 吧
# 这边先扣，那边先不加，等确认加
# 预期这边成功之后，用企业微信通知接收方，调转到查看未接收记录的窗口
@require_POST
@login_required(redirect_field_name='origin')
def start_transaction(request):
    recipient_id = request.POST.get('rid')  # index
    recipient_type = request.POST.get('rtype')
    origin = request.POST.get('origin')
    amount = request.POST.get('amount')
    transaction_msg = request.POST.get('msg')
    name = request.POST.get('name')
    context = dict()
    context['origin'] = origin

    # r_user = User.objects.get(username=recipient_id)

    try: 
        amount = float(amount)
    except:
        context['msg'] = 'Unexpected amount. If you are not deliberately doing this, please contact the administrator to report this bug.'
        return render(request, 'msg.html', context)


    try:
        if recipient_type == 'np':
            recipient = NaturalPerson.objects.get(pid=recipient_id).pid
        else:
            recipient = Organization.objects.get(oid=recipient_id).oid
    except:
        context['msg'] = 'Unexpected recipient. If you are not deliberately doing this, please contact the administrator to report this bug.'
        return render(request, 'msg.html', context)

    payer_id = request.session['username']
    if re.match('zz\d+', payer_id) is not None:
        payer = Organization.objects.get(oid=request.user)
    else:
        payer = NaturalPerson.objects.get(pid=request.user)


    try:
        if re.match('zz\d+', payer_id) is not None:
            payer = Organization.objects.select_for_update().filter(oid=request.user)
        else:
            payer = NaturalPerson.objects.select_for_update().filter(pid=request.user)
        with transaction.atomic():
            assert(len(payer) == 1)
            payer = payer[0]
            payer.YQPoint -= float(amount)
            # TODO 目前用的是 nickname，可能需要改成 name
            # 需要确认 create 是否会在数据库产生记录，如果不会是否会有主键冲突？
            record = TransferRecord.objects.create(proposer=request.user, recipient=recipient)
            record.amount = amount
            record.message = transaction_msg
            record.tstatus = 1 # Wating
            record.time = str(datetime.now())
            record.save()

            # TODO 确认 save 之后会释放锁？
            payer.save()

    except:
        context['msg'] = 'Check if you have enough YQPoint. If so, please contact the administrator to report this bug.'
        return render(request, 'msg.html', context)


    context['msg'] = 'Waiting the recipient to confirm the transaction.'
    return render(request, 'msg.html', context)


@require_GET
@login_required(redirect_field_name='origin')
def confirm_transaction(request):
    tid = request.GET.get('tid')
    reject = request.GET.get('reject')
    origin = request.GET.get('origin')
    if origin is None:
        origin = '/'
    context = dict()
    try:
        record = TransferRecord.objects.select_for_update().filter(id=tid)
        with transaction.atomic():
            assert(len(record) == 1)
            record = record[0]
            if record.recipient != request.user:
                context['msg'] = 'The transaction is not yours. If you are not deliberately doing this, please contact the administrator to report this bug.'
                return render(request, 'msg.html', context)
            if record.tstatus != 1:
                context['msg'] = 'The transaction has already been dealt. If you are not deliberately doing this, please contact the administrator to report this bug.'
                return render(request, 'msg.html', context)
            payer = record.proposer
            if re.match('zz\d+', payer.username) is not None:
                payer = Organization.objects.select_for_update().filter(oid=payer)
            else:
                payer = NaturalPerson.objects.select_for_update().filter(pid=payer)
            assert(len(payer) == 1)
            payer = payer[0]
            recipient = record.recipient
            if re.match('zz\d+', recipient.username) is not None:
                recipient = Organization.objects.select_for_update().filter(oid=recipient)
            else:
                recipient = NaturalPerson.objects.select_for_update().filter(pid=recipient)
            assert(len(recipient) == 1)
            recipient = recipient[0]
            if reject == 'True':
                record.tstatus = 2
                payer.YQPoint += record.amount
            else:
                record.tstatus = 0
                recipient.YQPoint += record.amount
            record.save()
            payer.save()
            recipient.save()
        context['msg'] = 'Confirmed transaction.'
        context['origin'] = origin
        return render(request, 'msg.html', context)
    except:
        context['msg'] = 'Can not find the transaction record. If you are not deliberately doing this, please contact the administrator to report this bug.'
        return render(request, 'msg.html', context)


