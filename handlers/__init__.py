from aiogram import Router

from handlers.subscriptions import router as subscriptions_router

router = Router()
router.include_router(subscriptions_router)
