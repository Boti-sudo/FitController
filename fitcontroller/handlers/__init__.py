from aiogram import Router

from fitcontroller.handlers.menu import router as menu_router
from fitcontroller.handlers.registration import router as registration_router
from fitcontroller.handlers.webapp import router as webapp_router

router = Router(name="handlers")
router.include_router(registration_router)
router.include_router(menu_router)
router.include_router(webapp_router)

__all__ = ["router"]
