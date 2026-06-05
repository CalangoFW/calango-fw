import pytest
from pydantic import ValidationError as PydanticValidationError

from calango.types import CalangoModel, OrderDirection, PaginatedResponse


class TestCalangoModel:
    def test_aceita_populacao_por_atributo(self):
        class Item(CalangoModel):
            name: str
            value: int

        item = Item.model_validate({"name": "test", "value": 42})
        assert item.name == "test"
        assert item.value == 42

    def test_aceita_populacao_por_orm_object(self):
        class FakeOrm:
            name = "produto"
            value = 10

        class Item(CalangoModel):
            name: str
            value: int

        item = Item.model_validate(FakeOrm())
        assert item.name == "produto"
        assert item.value == 10

    def test_serializa_para_dict(self):
        class Item(CalangoModel):
            name: str

        item = Item(name="test")
        assert item.model_dump() == {"name": "test"}

    def test_campo_invalido_levanta_erro(self):
        class Item(CalangoModel):
            value: int

        with pytest.raises(PydanticValidationError):
            Item(value="não é inteiro")  # ty: ignore[invalid-argument-type]  # intentional: non-int


class TestPaginatedResponse:
    def test_campos_obrigatorios(self):
        response: PaginatedResponse[str] = PaginatedResponse(
            items=["a", "b"],
            total=10,
            page=1,
            page_size=2,
        )
        assert response.items == ["a", "b"]
        assert response.total == 10
        assert response.page == 1
        assert response.page_size == 2

    def test_calcula_total_de_paginas(self):
        response: PaginatedResponse[str] = PaginatedResponse(
            items=["a"],
            total=25,
            page=1,
            page_size=10,
        )
        assert response.pages == 3

    def test_total_paginas_exato(self):
        response: PaginatedResponse[str] = PaginatedResponse(
            items=[],
            total=20,
            page=1,
            page_size=10,
        )
        assert response.pages == 2

    def test_total_zero_retorna_zero_paginas(self):
        response: PaginatedResponse[str] = PaginatedResponse(
            items=[],
            total=0,
            page=1,
            page_size=10,
        )
        assert response.pages == 0


class TestOrderDirection:
    def test_valores_existem(self):
        assert OrderDirection.ASC == "asc"
        assert OrderDirection.DESC == "desc"

    def test_e_string(self):
        assert isinstance(OrderDirection.ASC, str)
