from django.contrib.auth.base_user import BaseUserManager
class UserManager(BaseUserManager):
    def create_user(self, email, password):
        if not email:
            raise ValueError('Enter an email')
        user = self.model(email=email,is_suspended = False)
        user.set_password(password)
        user.save(using=self.db)
        return user
    def create_superuser(self, email, password):
        user = self.create_user(
            email=email,
            password=password)
        user.is_admin = True
        user.is_active = True
        
        user.is_superuser = True
        user.is_staff = True
        
        user.save(using=self._db)
        return user