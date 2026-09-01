"""Typed Open-Meteo request and forecast data."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


class WeatherForecastRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    start_date: date
    end_date: date
    timezone: str = Field(min_length=1)

    @model_validator(mode="after")
    def _date_range_is_forward(self) -> WeatherForecastRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days >= 16:
            raise ValueError("Open-Meteo forecasts at most 16 days")
        return self


class WeatherDay(BaseModel):
    date: date
    precipitation_probability_max: int = Field(ge=0, le=100)
    weather_code: int = Field(ge=0)
    precipitation_sum_mm: float = Field(ge=0)

    @property
    def is_rainy(self) -> bool:
        return self.precipitation_probability_max >= 50 or self.weather_code >= 51


class WeatherForecast(BaseModel):
    days: list[WeatherDay] = Field(default_factory=list)

    def for_date(self, value: date) -> WeatherDay | None:
        return next((day for day in self.days if day.date == value), None)


__all__ = ["WeatherDay", "WeatherForecast", "WeatherForecastRequest"]
