from .pelican import PelicanCog


async def setup(bot):
    await bot.add_cog(PelicanCog(bot))
