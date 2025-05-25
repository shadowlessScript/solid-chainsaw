import json
import logging
import random
import re
import jwt
from datetime import datetime, timedelta, timezone
from django.conf import settings
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import viewsets, status
from django.contrib.auth.models import Permission, Group
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from acl.utils import user_util
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.db.models import  Q
from django.db import transaction
from acl import models
from acl import serializers
from acl.utils import mailgun_general
from api import models as api_models
from api.serializers import FetchOverseerSerializer
import pyotp
from django.core.cache import cache

logger = logging.getLogger(__name__)

def password_generator():
        # generate password
        lower = "abcdefghijklmnopqrstuvwxyz"
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        numbers = "0123456789"
        symbols = "[}{$@]!?"

        sample_lower = random.sample(lower,2)
        sample_upper = random.sample(upper,2)
        sample_numbers = random.sample(numbers,2)
        sample_symbols = random.sample(symbols,2)

        all = sample_lower + sample_upper + sample_numbers + sample_symbols

        random.shuffle(all)

        password = "".join(all)
        # print(password)
        # end generate password
        return password

class OtpViewSet(viewsets.ModelViewSet):
    '''
      sends and verifies OTP    
    '''
    @action(methods=["POST"], detail=False, url_path="request-otp", url_name="request-otp")
    def send_otp(self, request):
        totp = pyotp.TOTP(pyotp.random_base32(), interval=120)
        otp = totp.now()  #TODO: Research how it works

        email = request.data.get('email')
        user_details = get_user_model().objects.get(email=email)
        otp_secret_key = totp.secret
        valid_date = datetime.now() + timedelta(minutes=2)
        print(otp_secret_key)
        # Store OTP data securely (avoid session storage in APIs)
        cache.set(f"otp_secret_{email}", otp_secret_key, timeout=120)  # Auto-expires in 2 mins
        cache.set(f"otp_valid_until_{email}", valid_date.isoformat(), timeout=120)
        subject = "One Time Password Details [NCC GDU]"
        message = f"\
                Dear user, \n\
                Your OTP is: {otp}\n\
                If you encounter any challenge while navigating the platform, please let us know.\
                "
        mailgun_general.send_mail(user_details.first_name,user_details.email,subject,message)
        return Response({"details":"Otp Sent"})
    
    @action(methods=["POST"],
                detail=False,
                url_path="verify-otp",
                url_name="verify-otp")
    def verify_otp(self, request):
        user_otp = request.data.get("otp")
        email = request.data.get("email")
        print(email, user_otp)
        otp_secret_key = cache.get(f"otp_secret_{email}")
        otp_valid_until = cache.get(f"otp_valid_until_{email}")
        print(otp_secret_key, otp_valid_until)
        if not otp_secret_key or not otp_valid_until:
            return Response({"details": "OTP  was not found"}, status=status.HTTP_400_BAD_REQUEST)

        valid_until = datetime.fromisoformat(otp_valid_until)
        if valid_until < datetime.now():
            return Response({"details": "OTP has expired"}, status=status.HTTP_400_BAD_REQUEST)

        totp = pyotp.TOTP(otp_secret_key, interval=120)  # Ensure interval matches generation
        print(totp.verify(user_otp))
        if totp.verify(user_otp):
            cache.delete(f"otp_secret_{email}")
            cache.delete(f"otp_valid_until_{email}")
            return Response({"details": "OTP verified successfully"}, status=status.HTTP_200_OK)

        return Response({"details": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)
    

class AuthenticationViewSet(viewsets.ModelViewSet):
    permission_classes = (AllowAny,)
    queryset = models.User.objects.all().order_by('id')
    serializer_class = serializers.SystemUsersSerializer
    search_fields = ['id', ]

    def get_queryset(self):
        return []


    @action(methods=["POST"], detail=False, url_path="login", url_name="login")
    def login_user(self, request):
        """
        Authenticates user. Provides access token. Takes username and password
        """
        payload = request.data
        email = request.data.get('email')
        password = request.data.get('password')
        if email is None:
            return Response({"details": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        if password is None:
            return Response({"details": "Password is required"}, status=status.HTTP_400_BAD_REQUEST)

        is_authenticated = authenticate(
            email=email, password=password)

        if is_authenticated: 

            is_suspended = is_authenticated.is_suspended
            if is_suspended is True or is_suspended is None:
                return Response({"details": "Your Account Has Been Suspended,Liase with your supervisor"}, status=status.HTTP_400_BAD_REQUEST)
            else:

                payload = {
                    'id': str(is_authenticated.id),
                    'email': is_authenticated.email,
                    'first_name': is_authenticated.first_name,
                    'staff': is_authenticated.is_staff,
                    'exp': datetime.utcnow() + timedelta(seconds=settings.TOKEN_EXPIRY),
                    'iat': datetime.utcnow()
                }
                token = jwt.encode(payload, settings.TOKEN_SECRET_CODE, algorithm="HS256")
                response_info = {
                    "token": token,
                }

                return Response(response_info, status=status.HTTP_200_OK)
        else:
            return Response({"details": "User not found"}, status=status.HTTP_400_BAD_REQUEST)
        
        
    @action(methods=["POST"], detail=False, url_path="create-account", url_name="create-account")
    def create_account(self, request):
        payload = request.data
        # print(payload)
        serializer = serializers.CreateUserSerializer(data=payload, many=False)
        if serializer.is_valid():
            with transaction.atomic():
                email = payload['email']
                first_name = payload['first_name']
                last_name = payload['last_name']
                password = payload['password']
                confirm_password = payload['confirm_password']
                
                userexists = get_user_model().objects.filter(email=email).exists()

                if userexists:
                    return Response({'details': 'User With Credentials Already Exist'}, status=status.HTTP_400_BAD_REQUEST)

               
                password_min_length = 8

                string_check= re.compile('[-@_!#$%^&*()<>?/\|}{~:;]') 

                if(password != confirm_password): 
                    return Response({'details':
                                     'Passwords Not Matching'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if(string_check.search(password) == None): 
                    return Response({'details':
                                     'Password Must contain a special character, choose one from these: [-@_!#$%^&*()<>?/\|}{~:;]'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if not any(char.isupper() for char in password):
                    return Response({'details':
                                     'Password must contain at least 1 uppercase letter'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if len(password) < password_min_length:
                    return Response({'details':
                                     'Password Must be atleast 8 characters'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if not any(char.isdigit() for char in password):
                    return Response({'details':
                                     'Password must contain at least 1 digit'},
                                    status=status.HTTP_400_BAD_REQUEST)
                                    
                if not any(char.isalpha() for char in password):
                    return Response({'details':
                                     'Password must contain at least 1 letter'},
                                    status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    group_details = Group.objects.get(name='USER')
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'Role does not exist'}, status=status.HTTP_400_BAD_REQUEST)
                            

                hashed_pwd = make_password(password)
                newuser = {
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_active": True,
                    "password": hashed_pwd,
                }
                create_user = get_user_model().objects.create(**newuser)

                group_details.user_set.add(create_user)
                user_util.log_account_activity(
                    create_user, create_user, "Account Creation",
                    "USER CREATED")
                

                return Response("success", status=status.HTTP_200_OK)

        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(methods=["POST"],
            detail=False,
            url_path="reset-user-password",
            url_name="reset-user-password")
    def reset_user_password(self, request):
        """
        Resets specific user password to default ie username. payload['user_id']
        """
        payload = request.data
        email = request.data.get('email')

        if email is None:
            return Response({"details": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            email = payload['email']
            try:
                user_details = get_user_model().objects.get(email=email)
            except (ValidationError, ObjectDoesNotExist):
                return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)

            new_password = password_generator()
            hashed_password = make_password(new_password)
            user_details.password = hashed_password
            user_details.save()

            subject = "Access Details [Nairobi GDU]"
            message = f"\
                            Dear user, \n\
                            Your email is {user_details.email}\n\
                            Your password is: {new_password}\n\
                            If you encounter any challenge while navigating the platform, please let us know.\
                        "
            mailgun_general.send_mail(user_details.first_name,user_details.email,subject,message)

            if not settings.DEBUG:
                new_password = '<REDACTED>'
            
            user_util.log_account_activity(
                user_details, user_details, "Password Reset", "Password Reset Executed")
            return Response(f"Password Reset Successful. Pass: {new_password}", status=status.HTTP_200_OK)

class AccountManagementViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.User.objects.all().order_by('id')
    serializer_class = serializers.SystemUsersSerializer
    search_fields = ['id', ]

    def get_queryset(self):
        return []

    @action(methods=["POST"], detail=False, url_path="change-password", url_name="change-password")
    def change_password(self, request):
        """
            Enables user to change password. Payload:  (new_password,confirm_password, current_password)
        """
        authenticated_user = request.user
        payload = request.data

        serializer = serializers.PasswordChangeSerializer(
            data=payload, many=False)
        if serializer.is_valid():
            with transaction.atomic():
                new_password = payload['new_password']
                confirm_password = payload['confirm_password']
                current_password = payload['current_password']
                password_min_length = 8

                string_check= re.compile('[-@_!#$%^&*()<>?/\|}{~:]') 

                if(string_check.search(new_password) == None): 
                    return Response({'details':
                                     'Password Must contain a special character'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if not any(char.isupper() for char in new_password):
                    return Response({'details':
                                     'Password must contain at least 1 uppercase letter'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if len(new_password) < password_min_length:
                    return Response({'details':
                                     'Password Must be atleast 8 characters'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if not any(char.isdigit() for char in new_password):
                    return Response({'details':
                                     'Password must contain at least 1 digit'},
                                    status=status.HTTP_400_BAD_REQUEST)
                                    
                if not any(char.isalpha() for char in new_password):
                    return Response({'details':
                                     'Password must contain at least 1 letter'},
                                    status=status.HTTP_400_BAD_REQUEST)
                try:
                    user_details = get_user_model().objects.get(id=authenticated_user.id)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)

                # check if new password matches current password
                encoded = user_details.password
                check_pass = check_password(new_password, encoded)
                if check_pass:
                    return Response({'details': 'New password should not be the same as old passwords'}, status=status.HTTP_400_BAD_REQUEST)


                if new_password != confirm_password:
                    return Response({"details": "Passwords Do Not Match"}, status=status.HTTP_400_BAD_REQUEST)
                is_current_password = authenticated_user.check_password(
                    current_password)
                if is_current_password is False:
                    return Response({"details": "Invalid Current Password"}, status=status.HTTP_400_BAD_REQUEST)
                else:
                    user_util.log_account_activity(
                        authenticated_user, user_details, "Password Change", "Password Change Executed")
                    existing_password = authenticated_user.password
                    user_details.is_defaultpassword = False
                    new_password_hash = make_password(new_password)
                    user_details.password = new_password_hash
                    user_details.last_password_reset = datetime.now()
                    user_details.save()
                    return Response("Password Changed Successfully", status=status.HTTP_200_OK)
        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


    @action(methods=["GET"], detail=False, url_path="list-users-with-role", url_name="list-users-with-role")
    def list_users_with_role(self, request):
        """
        Gets all users with a specific role. Payload: (role_name)
        """
        authenticated_user = request.user
        role_name = request.query_params.get('role_name')
        if role_name is None:
            return Response({'details': 'Role is Required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            role = Group.objects.get(name=role_name)
        except (ValidationError, ObjectDoesNotExist):
            return Response({'details': 'Role does not exist'}, status=status.HTTP_400_BAD_REQUEST)
        selected_users = get_user_model().objects.filter(groups__name=role.name)
        user_info = serializers.UsersSerializer(selected_users, many=True)
        return Response(user_info.data, status=status.HTTP_200_OK)
    

    @action(methods=["GET"], detail=False, url_path="get-account-activity", url_name="get-account-activity")
    def get_account_activity(self, request):
        """
        Gets account activity of a user. Payload: (account_id)
        """
        authenticated_user = request.user
        account_id = request.query_params.get('account_id')
        if account_id is None:
            return Response({'details': 'Account ID is Required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            account_instance = get_user_model().objects.get(id=account_id)
        except (ValidationError, ObjectDoesNotExist):
            return Response({'details': 'Account does not exist'}, status=status.HTTP_400_BAD_REQUEST)
        selected_records = []
        if hasattr(account_instance, 'user_account_activity'):
            selected_records = account_instance.user_account_activity.all()
        user_info = serializers.AccountActivitySerializer(
            selected_records, many=True)
        return Response(user_info.data, status=status.HTTP_200_OK)
    

    @action(methods=["GET"], detail=False, url_path="get-account-activity-detail", url_name="get-account-activity-detail")
    def get_account_activity_detail(self, request):
        """
        Gets single account activity detail information of a user. Payload: (request_id)
        """
        authenticated_user = request.user
        request_id = request.query_params.get('request_id')
        if request_id is None:
            return Response({'details': 'Request ID is Required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            account_activity_instance = models.AccountActivity.objects.get(
                id=request_id)
        except (ValidationError, ObjectDoesNotExist):
            return Response({'details': 'Request does not exist'}, status=status.HTTP_400_BAD_REQUEST)
        account_info = serializers.AccountActivityDetailSerializer(
            account_activity_instance, many=False)
        return Response(account_info.data, status=status.HTTP_200_OK)
    

    @action(methods=["GET"], detail=False, url_path="list-roles", url_name="list-roles")
    def list_roles(self, request):
        """
        Gets all available roles 
        """
        authenticated_user = request.user
        role = Group.objects.all()
        record_info = serializers.RoleSerializer(role, many=True)
        return Response(record_info.data, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False, url_path="list-user-roles", url_name="list-user-roles")
    def list_user_roles(self, request):
        """
        Gets roles for a logged in user.
        """
        authenticated_user = request.user
        role = user_util.fetchusergroups(authenticated_user.id)

        rolename = {
            "group_name": role
        }
        return Response(rolename, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False, url_path="get-user-details", url_name="get-user-details")
    def get_user_details(self, request):
        """
        Gets specific user details. Payload: (user_id)
        """
        authenticated_user = request.user
        user_id = request.query_params.get('user_id')
        if user_id is None:
            return Response({'details': 'Invalid Filter Criteria'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user_details = get_user_model().objects.get(id=user_id)
        except (ValidationError, ObjectDoesNotExist):
            return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST) 
    
        user_info = serializers.UsersSerializer(user_details, many=False)
        return Response(user_info.data, status=status.HTTP_200_OK)



    @action(methods=["GET"], detail=False, url_path="filter-by-username", url_name="filter-by-username")
    def filter_by_username(self, request):
        """
        searches User by username: Payload ('username')
        """
        authenticated_user = request.user
        username = request.query_params.get('username')
        # if username is None:
        #     return Response({'details': 'Invalid Filter Criteria'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            if username == "all":
                user_details = get_user_model().objects.all()
                user_info = serializers.UsersSerializer(user_details, many=True).data
                overseers = api_models.Overseer.objects.all()
                seers = FetchOverseerSerializer(overseers, many=True).data
                resp = user_info + seers
                return Response(resp, status=status.HTTP_200_OK)
            elif username and username != "all":
                user_details = get_user_model().objects.filter(Q(email__icontains=username) | Q(first_name__icontains=username) | Q(last_name__icontains=username))
            elif username is None or not username:
                user_details = get_user_model().objects.all()
                print(len(user_details))
        except (ValidationError, ObjectDoesNotExist):
            return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)
        
        user_info = serializers.UsersSerializer(user_details, many=True)
        return Response(user_info.data, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False, url_path="get-profile-details", url_name="get-profile-details")
    def get_profile_details(self, request):
        """
        Retrievs logged in user profile
        """
        authenticated_user = request.user
        payload = request.data
        try:
            user_details = get_user_model().objects.get(id=authenticated_user.id)
        except (ValidationError, ObjectDoesNotExist):
            return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)
        user_info = serializers.UsersSerializer(user_details, many=False)
        return Response(user_info.data, status=status.HTTP_200_OK)

class ICTSupportViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.User.objects.all().order_by('id')
    serializer_class = serializers.SystemUsersSerializer
    search_fields = ['id', ]

    def get_queryset(self):
        return []

    @action(methods=["POST"],
            detail=False,
            url_path="reset-user-password",
            url_name="reset-user-password")
    def reset_user_password(self, request):
        """
        Resets specific user password to default ie username. payload['user_id']
        """
        authenticated_user = request.user
        payload = request.data
        serializer = serializers.UserIdSerializer(data=payload, many=False)
        if serializer.is_valid():
            with transaction.atomic():
                userid = payload['user_id']
                try:
                    user_details = get_user_model().objects.get(id=userid)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)

                new_password = self.password_generator()
                hashed_password = make_password(new_password)
                user_details.password = hashed_password
                user_details.save()

                subject = "Access Details [Nairobi GDU]"
                message = f"\
                                Dear user, \n\
                                Your email is {user_details.email}\n\
                                Your password is: {new_password}\n\
                                If you encounter any challenge while navigating the platform, please let us know.\
                            "
                mailgun_general.send_mail(user_details.first_name,user_details.email,subject,message)

                if not settings.DEBUG:
                    new_password = '<REDACTED>'
                
                user_util.log_account_activity(
                    authenticated_user, user_details, "Password Reset", "Password Reset Executed")
                return Response(f"Password Reset Successful. Pass: {new_password}", status=status.HTTP_200_OK)
        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST"], detail=False, url_path="swap-user-department", url_name="swap-user-department")
    def swap_user_department(self, request):
        """
        Switches user from one department to another. payload['department_id','user_id']
        """
        authenticated_user = request.user
        payload = request.data
        serializer = serializers.SwapUserDepartmentSerializer(
            data=payload, many=False)
        if serializer.is_valid():
            with transaction.atomic():
                department_id = payload['department_id']
                user_id = payload['user_id']
                try:
                    user_details = get_user_model().objects.get(id=user_id)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    department_details = models.Department.objects.get(
                        id=department_id)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'Department does not exist'}, status=status.HTTP_400_BAD_REQUEST)
                user_details.department = department_details
                user_details.save()
                user_util.log_account_activity(
                    authenticated_user, user_details, "Department Swap", "Department Was Swapped")
                return Response("Department Successfully Changed", status=status.HTTP_200_OK)
        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST"],
            detail=False,
            url_path="edit-user",
            url_name="edit-user")
    def edit_user(self, request):
        """
        Updates user details. payload['id_number','first_name','last_name','account_id']
        """
        payload = json.loads(request.data.get('payload'))
        authenticated_user = request.user
        serializer = serializers.EditUserSerializer(data=payload, many=False)
        if serializer.is_valid():
            # id_number = payload['id_number']
            first_name = payload['first_name']
            last_name = payload['last_name']
            account_id = payload['account_id']
            # phone_number = payload['phone_number']
            # email = payload['email']


            # phoneexists = get_user_model().objects.filter(phone_number=phone_number).exists()
            # emailexists = get_user_model().objects.filter(email=email).exists()

                            
            try:
                record_instance = get_user_model().objects.get(id=account_id)
            except (ValidationError, ObjectDoesNotExist):
                return Response(
                    {'details': 'User does not exist'},
                    status=status.HTTP_400_BAD_REQUEST)

                               

            record_instance.first_name = first_name
            record_instance.last_name = last_name

            record_instance.save()

            user_util.log_account_activity(
                        authenticated_user, authenticated_user, "Updated Profile",
                        "PROFILE UPDATION")

            return Response("Successfully Updated",
                            status=status.HTTP_200_OK)

        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST"],
            detail=False,
            url_path="award-role",
            url_name="award-role")
    def award_role(self, request):
        """
        Gives user a new role. payload['role_id','account_id']
        """
        payload = request.data
        authenticated_user = request.user
        serializer = serializers.ManageRoleSerializer(data=payload, many=False)
        if serializer.is_valid():
            role_id = payload['role_id']
            account_id = payload['account_id']
            if not role_id:
                return Response(
                    {'details': 'Select atleast one role'},
                    status=status.HTTP_400_BAD_REQUEST)

            try:
                record_instance = get_user_model().objects.get(id=account_id)
            except (ValidationError, ObjectDoesNotExist):
                return Response(
                    {'details': 'Invalid User'},
                    status=status.HTTP_400_BAD_REQUEST)
            group_names = []
            for assigned_role in role_id:
                group = Group.objects.get(id=assigned_role)
                group_names.append(group.name)

                record_instance.groups.add(group)
            user_util.log_account_activity(
                authenticated_user, record_instance, "Role Assignment",
                "USER ASSIGNED ROLES {{i}}".format(group_names))
            return Response("Successfully Updated",
                            status=status.HTTP_200_OK)

        else:
            return Response({"details": serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST"],
            detail=False,
            url_path="revoke-role",
            url_name="revoke-role")
    def revoke_role(self, request):
        """
        Revokes a role assigned to a user. payload['role_id','account_id']
        """
        payload = request.data
        authenticated_user = request.user
        serializer = serializers.ManageRoleSerializer(data=payload, many=False)
        if serializer.is_valid():
            role_id = payload['role_id']
            account_id = payload['account_id']
            if not role_id:
                return Response(
                    {'details': 'Select atleast one role'},
                    status=status.HTTP_400_BAD_REQUEST)

            try:
                record_instance = get_user_model().objects.get(id=account_id)
            except (ValidationError, ObjectDoesNotExist):
                return Response(
                    {'details': 'Invalid User'},
                    status=status.HTTP_400_BAD_REQUEST)
            group_names = []
            for assigned_role in role_id:
                group = Group.objects.get(id=assigned_role)
                group_names.append(group.name)
                record_instance.groups.remove(group)
            user_util.log_account_activity(
                authenticated_user, record_instance, "Role Revokation",
                "USER REVOKED ROLES {{i}}".format(group_names))
            return Response("Successfully Updated",
                            status=status.HTTP_200_OK)

        else:
            return Response({"details": serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST)

    def password_generator(self):
        # generate password
        lower = "abcdefghijklmnopqrstuvwxyz"
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        numbers = "0123456789"
        symbols = "[}{$@]!?"

        sample_lower = random.sample(lower,2)
        sample_upper = random.sample(upper,2)
        sample_numbers = random.sample(numbers,2)
        sample_symbols = random.sample(symbols,2)

        all = sample_lower + sample_upper + sample_numbers + sample_symbols

        random.shuffle(all)

        password = "".join(all)
        # print(password)
        # end generate password
        return password

    @action(methods=["POST"], detail=False, url_path="create-user", url_name="create-user")
    def create_user(self, request):
        """
        Creates a new user in the system. payload['id_number','username','first_name','last_name','department_id','role_name']
        """
        payload = request.data
        authenticated_user = request.user
        serializer = serializers.UserDetailSerializer(data=payload, many=False)
        if serializer.is_valid():
            with transaction.atomic():
                first_name = payload['first_name']
                last_name = payload['last_name']
                email = payload['email']
                role_name = payload['role_name']
                emailexists = get_user_model().objects.filter(email=email).exists()


                if emailexists:
                    return Response({'details': 'User With Credentials Already Exist'}, status=status.HTTP_400_BAD_REQUEST)
                

                
                try:
                    group_details = Group.objects.get(id=role_name)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'Role does not exist'}, status=status.HTTP_400_BAD_REQUEST)



                password = self.password_generator()

                hashed_pwd = make_password(password)
                newuser = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "is_active": True,
                    "is_superuser": False,
                    "is_staff": False,
                    "is_suspended": False,
                    "password": hashed_pwd,
                }
                create_user = get_user_model().objects.create(**newuser)
                group_details.user_set.add(create_user)


                subject = "Platform Access Details [Nairobi GDU]"
                message = f"\
                                Dear user, \n\
                                Your email is {email}\n\
                                Your password is: {password}\n\
                                If you encounter any challenge while navigating the platform, please let us know.\
                            "
                mailgun_general.send_mail(first_name,email,subject,message)

                user_util.log_account_activity(
                    authenticated_user, create_user, "Account Creation",
                    "USER CREATED")
                
                if not settings.DEBUG:
                    password = ''


                info = {
                    'success': 'User Created Successfully',
                    'password': password
                }
                return Response(info, status=status.HTTP_200_OK)

        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST"], detail=False, url_path="suspend-user", url_name="suspend-user")
    def suspend_user(self, request):
        """
        Suspends a user. payload['user_id','remarks']
        """
        authenticated_user = request.user
        payload = request.data
        serializer = serializers.SuspendUserSerializer(
            data=payload, many=False)
        if serializer.is_valid():
            with transaction.atomic():
                user_id = payload['user_id']
                remarks = payload['remarks']
                try:
                    user_details = get_user_model().objects.get(id=user_id)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)

                user_details.is_suspended = True
                user_util.log_account_activity(
                    authenticated_user, user_details, "Account Suspended", remarks)
                user_details.save()
                return Response("Account Successfully Changed", status=status.HTTP_200_OK)
        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST"], detail=False, url_path="un-suspend-user", url_name="un-suspend-user")
    def un_suspend_user(self, request):
        """
        Unsuspends a user. payload['user_id','remarks']
        """
        authenticated_user = request.user
        payload = request.data
        serializer = serializers.SuspendUserSerializer(
            data=payload, many=False)
        if serializer.is_valid():
            user_id = payload['user_id']
            remarks = payload['remarks']
            with transaction.atomic():
                try:
                    user_details = get_user_model().objects.get(id=user_id)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({'details': 'User does not exist'}, status=status.HTTP_400_BAD_REQUEST)

                user_details.is_suspended = False
                user_util.log_account_activity(
                    authenticated_user, user_details, "Account UnSuspended", remarks)
                user_details.save()
                return Response("Account Unsuspended", status=status.HTTP_200_OK)
        else:
            return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        

