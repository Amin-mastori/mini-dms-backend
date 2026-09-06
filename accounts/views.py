import logging

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from accounts.serializers import CreateUserSerializer, UserSerializer

logger = logging.getLogger("dms.accounts")


class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class LogoutView(TokenBlacklistView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class MeView(APIView):
    @extend_schema(responses=UserSerializer, tags=["Accounts"])
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAdminUser]
    queryset = get_user_model().objects.order_by("id")
    serializer_class = UserSerializer

    def get_serializer_class(self):
        return CreateUserSerializer if self.request.method == "POST" else UserSerializer

    @extend_schema(request=CreateUserSerializer, responses={201: UserSerializer}, tags=["Accounts"])
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info("user_provisioned", extra={"actor_id": request.user.pk})
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
